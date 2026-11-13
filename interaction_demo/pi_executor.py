"""Laptop side: sends one command to the Pi agent and returns a result for Campaign.run_pending."""
import json, os, urllib.request, urllib.error


def execute(command, url=None, token=None, timeout=15):
    url = (url or os.environ["CHIPCHECK_PI_URL"]).rstrip("/")
    token = token or os.environ.get("CHIPCHECK_PI_TOKEN", "")
    ids = {k: command[k] for k in ("campaign_id", "batch_id", "experiment_id")}
    req = urllib.request.Request(url + "/run", data=json.dumps(command).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        return {**ids, "status": "ABORTED", "applied_parameters": dict(command["parameters"]), "measurements": {},
                "outcome": "ABORTED", "measurement_quality": "INVALID", "source": "raspberry-pi", "error": str(e)}
    return {**ids, "status": "COMPLETED", **body}
