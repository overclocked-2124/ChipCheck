"""HTTP/JSON API of the control plane (HLD 05 §4-§7).

``Api.handle`` turns a ``Request`` into a ``Response`` and is independent of sockets, so it is tested
directly; ``ApiServer`` is the thin stdlib HTTP shell around it. The API holds no rules: it authenticates,
parses, calls Backend and maps errors to the HLD 05 §4.1 error model. It listens on loopback only
(HLD 07 §3); bench endpoints accept the fixture's bearer token and nothing else.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, urlsplit

from activequal.model.errors import InvalidRequest
from activequal.service import queries, views
from activequal.service.auth import AuthConfig, bearer_token
from activequal.service.backend import Actor, Backend
from activequal.service.errors import BackendError, invalid, not_found

log = logging.getLogger("activequal.api")

MAX_JSON_BYTES = 2_000_000
MAX_TRACE_BYTES = 256 * 1024 * 1024
SSE_POLL_S = 0.5
SSE_KEEPALIVE_S = 15.0
SSE_MAX_S = 3600.0


class Headers(dict):
    """Case-insensitive header lookup over a plain dict."""

    def __init__(self, items: dict[str, str] | None = None) -> None:
        super().__init__({k.lower(): v for k, v in (items or {}).items()})

    def get(self, key: str, default: Any = None) -> Any:       # type: ignore[override]
        return super().get(key.lower(), default)


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: Headers = field(default_factory=Headers)
    body: Callable[[], bytes] = lambda: b""


@dataclass
class Response:
    status: int
    body: Any = None                                  # JSON-serializable, or bytes with content_type
    content_type: str = "application/json"
    stream: Iterator[bytes] | None = None             # server-sent events


def _json_body(request: Request) -> dict[str, Any]:
    raw = request.body()
    if len(raw) > MAX_JSON_BYTES:
        raise invalid("request body is too large")
    try:
        value = json.loads(raw or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise invalid(f"body is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise invalid("body must be a JSON object")
    return value


def _field(body: dict[str, Any], name: str, kind: type | tuple[type, ...], *, optional: bool = False) -> Any:
    if name not in body or body[name] is None:
        if optional:
            return None
        raise invalid(f"{name} is required")
    value = body[name]
    if isinstance(value, bool) and kind is not bool and bool not in (kind if isinstance(kind, tuple) else (kind,)):
        raise invalid(f"{name} has the wrong type")
    if not isinstance(value, kind):
        raise invalid(f"{name} has the wrong type")
    return value


def _time(text: str, name: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise invalid(f"{name} must be an RFC 3339 time") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


CAMPAIGN_ACTIONS = ("validate", "arm", "start", "pause", "resume", "abort", "disarm", "clear-lockout")
ROUTES: list[tuple[str, re.Pattern[str], str, str]] = [
    # method, path, handler, auth ("human" | "reviewer" | "bench" | "none")
    ("GET", re.compile(r"^/healthz$"), "healthz", "none"),
    ("GET", re.compile(r"^/metrics$"), "metrics", "none"),
    ("POST", re.compile(r"^/v1/contracts$"), "create_contract", "human"),
    ("GET", re.compile(r"^/v1/contracts$"), "list_contracts", "human"),
    ("POST", re.compile(r"^/v1/contracts/(?P<id>[^/:]+)/versions/(?P<version>\d+):approve$"), "approve_contract", "reviewer"),
    ("GET", re.compile(r"^/v1/contracts/(?P<id>[^/:]+)/versions/(?P<version>\d+)$"), "get_contract", "human"),
    ("POST", re.compile(r"^/v1/fixtures$"), "register_fixture", "reviewer"),
    ("GET", re.compile(r"^/v1/fixtures$"), "list_fixtures", "human"),
    ("GET", re.compile(r"^/v1/fixtures/(?P<id>[^/:]+)$"), "get_fixture", "human"),
    ("POST", re.compile(r"^/v1/fixtures/(?P<id>[^/:]+)/calibrations$"), "record_calibration", "human"),
    ("POST", re.compile(r"^/v1/fixtures/(?P<id>[^/:]+):rotate-token$"), "rotate_token", "reviewer"),
    ("POST", re.compile(r"^/v1/campaigns$"), "create_campaign", "human"),
    ("GET", re.compile(r"^/v1/campaigns$"), "list_campaigns", "human"),
    ("POST", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+):(?P<action>" + "|".join(CAMPAIGN_ACTIONS) + ")$"),
     "campaign_action", "human"),          # clear-lockout upgrades itself to reviewer below
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)$"), "get_campaign", "human"),
    ("POST", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/manual-candidates$"), "manual_candidate", "human"),
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/events$"), "campaign_events", "human"),
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/episodes$"), "campaign_episodes", "human"),
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/counterexamples$"), "campaign_counterexamples", "human"),
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/export$"), "campaign_export", "human"),
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/report$"), "campaign_report", "human"),
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/records$"), "campaign_records", "human"),
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/contract$"), "campaign_contract", "human"),
    ("GET", re.compile(r"^/v1/campaigns/(?P<id>[^/:]+)/lease$"), "campaign_lease", "human"),
    ("GET", re.compile(r"^/v1/compare$"), "compare", "human"),
    ("GET", re.compile(r"^/v1/episodes/(?P<id>[^/:]+)$"), "get_episode", "human"),
    ("POST", re.compile(r"^/v1/leases/(?P<id>[^/:]+):reconcile$"), "reconcile_lease", "reviewer"),
    ("POST", re.compile(r"^/v1/proposals$"), "proposals", "human"),
    ("POST", re.compile(r"^/v1/bench/claim$"), "bench_claim", "bench"),
    ("POST", re.compile(r"^/v1/bench/leases/(?P<id>[^/:]+):heartbeat$"), "bench_heartbeat", "bench"),
    ("POST", re.compile(r"^/v1/bench/leases/(?P<id>[^/:]+):abort-ack$"), "bench_abort_ack", "bench"),
    ("POST", re.compile(r"^/v1/bench/episodes/(?P<id>[^/:]+)/results$"), "bench_results", "bench"),
    ("PUT", re.compile(r"^/v1/bench/traces/(?P<sha>[0-9a-f]{64})$"), "bench_trace", "bench"),
    ("POST", re.compile(r"^/v1/bench/health$"), "bench_health", "bench"),
]


class Api:
    def __init__(self, backend: Backend, auth: AuthConfig, propose: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 runner: Any = None, exporter: Callable[[Backend, str], dict[str, Any]] | None = None) -> None:
        self.backend, self.auth, self.propose, self.runner, self.exporter = backend, auth, propose, runner, exporter

    # ------------------------------------------------------------------ dispatch

    def handle(self, request: Request) -> Response:
        try:
            path_matched = False
            for method, pattern, name, kind in ROUTES:
                match = pattern.match(request.path)
                if match is None:
                    continue
                path_matched = True
                if method != request.method:
                    continue
                params = match.groupdict()
                if name == "campaign_action" and params["action"] == "clear-lockout":
                    kind = "reviewer"
                return getattr(self, "_" + name)(request, self._authenticate(request, kind), params)
            if path_matched:
                raise BackendError("METHOD_NOT_ALLOWED", f"{request.method} is not allowed here")
            raise not_found("route")
        except BackendError as exc:
            return Response(exc.status, exc.body())
        except InvalidRequest as exc:
            return Response(400, BackendError("INVALID_ARGUMENT", str(exc)).body())
        except Exception:
            log.exception("unhandled error for %s %s", request.method, request.path)
            return Response(500, {"error": {"code": "INTERNAL", "message": "internal error", "details": {}}})

    def _authenticate(self, request: Request, kind: str) -> Actor | str | None:
        if kind == "none":
            return None
        if kind == "bench":
            return self.backend.authenticate_bench(bearer_token(request.headers))     # -> fixture id
        return self.auth.human_actor(request.headers, need_reviewer=kind == "reviewer")

    # ------------------------------------------------------------------- general

    def _healthz(self, request, actor, params) -> Response:
        self.backend.db.one("SELECT 1")
        return Response(200, {"status": "ok", "software": self.backend.software_version,
                              "runnerErrors": dict(getattr(self.runner, "errors", {}) or {})})

    def _metrics(self, request, actor, params) -> Response:
        return Response(200, queries.metrics_text(self.backend).encode(), "text/plain; version=0.0.4")

    def _proposals(self, request, actor, params) -> Response:
        if self.propose is None:
            raise BackendError("UNAVAILABLE", "the Decision Service is not available")
        return Response(200, self.propose(_json_body(request)))

    # ----------------------------------------------------------------- contracts

    def _create_contract(self, request, actor, params) -> Response:
        body = _json_body(request)
        created = self.backend.create_contract(_field(body, "contract", dict), actor,
                                               _field(body, "contractId", str, optional=True))
        return Response(201, created)

    def _approve_contract(self, request, actor, params) -> Response:
        return Response(200, self.backend.approve_contract(params["id"], int(params["version"]), actor))

    def _get_contract(self, request, actor, params) -> Response:
        return Response(200, self.backend.get_contract(params["id"], int(params["version"])))

    # ------------------------------------------------------------------ fixtures

    def _register_fixture(self, request, actor, params) -> Response:
        body = _json_body(request)
        created = self.backend.register_fixture(
            _field(body, "fixtureId", str), _field(body, "revision", str), _field(body, "capabilities", list), actor,
            _field(body, "approvedMcuFirmwareSha256", str, optional=True))
        return Response(201, created)

    def _get_fixture(self, request, actor, params) -> Response:
        return Response(200, queries.fixture_view(self.backend, params["id"]))

    def _record_calibration(self, request, actor, params) -> Response:
        body = _json_body(request)
        created = self.backend.record_calibration(
            params["id"], _field(body, "channels", dict), _field(body, "meterIdentity", str),
            _field(body, "operator", str), _time(_field(body, "validUntil", str), "validUntil"), actor)
        return Response(201, created)

    def _rotate_token(self, request, actor, params) -> Response:
        return Response(200, self.backend.rotate_bench_token(params["id"], actor))

    # ----------------------------------------------------------------- campaigns

    def _create_campaign(self, request, actor, params) -> Response:
        body = _json_body(request)
        created = self.backend.create_campaign(
            _field(body, "contractId", str), _field(body, "version", int), _field(body, "fixtureId", str),
            _field(body, "planner", str), _field(body, "seed", int), _field(body, "discoveryBudget", int),
            _field(body, "verificationBudget", int), actor, _field(body, "plannerConfig", dict, optional=True))
        return Response(201, created)

    def _list_campaigns(self, request, actor, params) -> Response:
        return Response(200, {"campaigns": queries.list_campaigns(self.backend)})

    def _get_campaign(self, request, actor, params) -> Response:
        view = self.backend.get_campaign(params["id"])
        if self.runner is not None and params["id"] in self.runner.errors:
            view = {**view, "agentError": self.runner.errors[params["id"]]}
        return Response(200, view)

    def _campaign_action(self, request, actor, params) -> Response:
        body = _json_body(request)
        version = _field(body, "campaignVersion", int)
        cid, action, b = params["id"], params["action"], self.backend
        if action == "validate":
            return Response(200, b.validate_campaign(cid, version, actor))
        if action == "arm":
            return Response(200, b.arm_campaign(cid, version, actor))
        if action == "start":
            return Response(200, b.start_campaign(cid, version, actor))
        if action == "pause":
            return Response(200, b.pause_campaign(cid, version, actor))
        if action == "resume":
            return Response(200, b.resume_campaign(cid, version, actor))
        if action == "abort":
            return Response(200, b.abort_campaign(cid, version, actor))
        if action == "disarm":
            return Response(200, b.abort_campaign(cid, version, actor, disarm=True))
        return Response(200, b.clear_lockout(cid, version, actor,
                                              physical_inspection=_field(body, "physicalInspection", bool),
                                              note=_field(body, "note", str)))

    def _manual_candidate(self, request, actor, params) -> Response:
        body = _json_body(request)
        note = (_field(body, "note", str, optional=True) or "").strip()
        result = self.backend.submit_candidate(
            params["id"], None, _field(body, "conditions", dict),
            planner_reason="Operator-chosen candidate" + (f": {note}" if note else ""), reason_code="MANUAL", actor=actor)
        return Response(201, result)

    def _campaign_episodes(self, request, actor, params) -> Response:
        return Response(200, {"episodes": self.backend.episode_history(params["id"]),
                              "rejected": self.backend.rejected_conditions(params["id"])})

    def _campaign_counterexamples(self, request, actor, params) -> Response:
        return Response(200, {"counterexamples": self.backend.counterexamples(params["id"])})

    def _campaign_export(self, request, actor, params) -> Response:
        if self.exporter is None:
            raise BackendError("UNAVAILABLE", "report export is not configured")
        return Response(200, self.exporter(self.backend, params["id"]))

    def _get_episode(self, request, actor, params) -> Response:
        return Response(200, views.episode_detail(self.backend, params["id"]))

    # ------------------------------------------------------- Console read views (HLD 09 §5)

    def _list_contracts(self, request, actor, params) -> Response:
        return Response(200, {"contracts": views.list_contracts(self.backend)})

    def _list_fixtures(self, request, actor, params) -> Response:
        return Response(200, {"fixtures": views.list_fixtures(self.backend)})

    def _campaign_report(self, request, actor, params) -> Response:
        return Response(200, views.campaign_report(self.backend, params["id"]))

    def _campaign_records(self, request, actor, params) -> Response:
        return Response(200, views.campaign_records(self.backend, params["id"]))

    def _campaign_contract(self, request, actor, params) -> Response:
        return Response(200, views.campaign_contract(self.backend, params["id"]))

    def _campaign_lease(self, request, actor, params) -> Response:
        return Response(200, views.campaign_lease(self.backend, params["id"]))

    def _compare(self, request, actor, params) -> Response:
        return Response(200, views.compare(self.backend, request.query.get("campaigns", "").split(",")))

    def _reconcile_lease(self, request, actor, params) -> Response:
        body = _json_body(request)
        return Response(200, self.backend.reconcile_lease(params["id"], _field(body, "resolution", str),
                                                           _field(body, "note", str), actor))

    def _campaign_events(self, request, actor, params) -> Response:
        cid = params["id"]
        try:
            after = int(request.query.get("after", "0"))
        except ValueError as exc:
            raise invalid("after must be an integer") from exc
        self.backend.get_campaign(cid)                        # 404 for unknown campaigns
        if "text/event-stream" not in (request.headers.get("Accept") or ""):
            return Response(200, {"events": self.backend.list_events(cid, after)})
        return Response(200, stream=self._sse(cid, after), content_type="text/event-stream")

    def _sse(self, campaign_id: str, after: int) -> Iterator[bytes]:
        started = last_send = time.monotonic()
        yield b": connected\n\n"
        while time.monotonic() - started < SSE_MAX_S:
            events = self.backend.list_events(campaign_id, after)
            for event in events:
                after = event["id"]
                yield f"id: {event['id']}\nevent: {event['entity']}\ndata: {json.dumps(event)}\n\n".encode()
                last_send = time.monotonic()
            if not events:
                if time.monotonic() - last_send > SSE_KEEPALIVE_S:
                    yield b": keepalive\n\n"
                    last_send = time.monotonic()
                time.sleep(SSE_POLL_S)

    # --------------------------------------------------------------------- bench

    def _bench_claim(self, request, fixture_id, params) -> Response:
        body = _json_body(request)
        claim = self.backend.claim_episode(fixture_id, _field(body, "controllerInstanceId", str))
        return Response(204) if claim is None else Response(200, claim)

    def _bench_heartbeat(self, request, fixture_id, params) -> Response:
        body = _json_body(request)
        return Response(200, self.backend.heartbeat(params["id"], fixture_id, _field(body, "phase", str, optional=True)))

    def _bench_abort_ack(self, request, fixture_id, params) -> Response:
        return Response(200, self.backend.acknowledge_abort(params["id"], fixture_id))

    def _bench_results(self, request, fixture_id, params) -> Response:
        body = _json_body(request)
        if body.get("episodeId") != params["id"]:
            raise invalid("episodeId in the body must match the path")
        return Response(200, self.backend.submit_result(body, fixture_id))

    def _bench_trace(self, request, fixture_id, params) -> Response:
        raw = request.body()
        media = request.headers.get("Content-Type") or "application/octet-stream"
        return Response(200, self.backend.put_trace(params["sha"], raw, media, fixture_id))

    def _bench_health(self, request, fixture_id, params) -> Response:
        return Response(200, self.backend.record_bench_health(fixture_id, _json_body(request)))


# ------------------------------------------------------------------------ server

def require_loopback(host: str) -> None:
    """The control plane never listens beyond the workstation (HLD 07 §3)."""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError(f"refusing to listen on {host!r}: the control plane is loopback-only in the MVP")


class ApiServer:
    def __init__(self, api: Api, host: str = "127.0.0.1", port: int = 8001) -> None:
        require_loopback(host)
        handler = self._handler(api)
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self.thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @staticmethod
    def _handler(api: Api):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                log.debug("%s " + fmt, self.address_string(), *args)

            def _read(self) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                limit = MAX_TRACE_BYTES if self.command == "PUT" else MAX_JSON_BYTES
                if length < 0 or length > limit:
                    raise invalid("request body is too large")
                return self.rfile.read(length)

            def _serve(self) -> None:
                parts = urlsplit(self.path)
                query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
                request = Request(self.command, parts.path, query, Headers(dict(self.headers.items())), self._read)
                response = api.handle(request)
                if response.stream is not None:
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.content_type)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    try:
                        for chunk in response.stream:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                if isinstance(response.body, bytes):
                    payload = response.body
                else:
                    payload = b"" if response.body is None else json.dumps(response.body).encode()
                self.send_response(response.status)
                if response.status != 204:
                    self.send_header("Content-Type", response.content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = _serve

        return Handler

    def start(self) -> None:
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="api", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
