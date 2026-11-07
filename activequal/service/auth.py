"""Authentication for the control plane's HTTP API (HLD 07 §5, §7).

Human requests (the Console's server routes) carry an operator token, a recorded operator name,
and, for reviewer actions, the reviewer passphrase. Bench requests carry the per-fixture bearer
token and nothing else, and a bench token can reach only the bench endpoints. Loopback binding
alone does not authenticate a caller, so every request is checked. This defends against
accidents (a researcher approving their own change, a stray local process), not a determined
local user (HLD 07 §2).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from typing import Mapping

from activequal.service.backend import RESEARCHER, REVIEWER, Actor
from activequal.service.errors import BackendError

OPERATOR_TOKEN_HEADER = "X-ActiveQual-Operator-Token"
ACTOR_HEADER = "X-ActiveQual-Actor"
PASSPHRASE_HEADER = "X-ActiveQual-Reviewer-Passphrase"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,59}$")
MIN_TOKEN_LENGTH = 24
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def hash_passphrase(passphrase: str, salt: bytes | None = None) -> str:
    """``scrypt$<salt>$<hash>`` for the workstation config file."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(passphrase.encode(), salt=salt, **SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_passphrase(passphrase: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(passphrase.encode(), salt=base64.b64decode(salt_b64), **SCRYPT)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@dataclass(frozen=True)
class AuthConfig:
    operator_token: str
    reviewer_passphrase_hash: str

    def __post_init__(self) -> None:
        if len(self.operator_token) < MIN_TOKEN_LENGTH:
            raise ValueError(f"the operator token must be at least {MIN_TOKEN_LENGTH} characters")
        if not self.reviewer_passphrase_hash.startswith("scrypt$"):
            raise ValueError("reviewer_passphrase_hash must come from hash_passphrase()")

    def human_actor(self, headers: Mapping[str, str], *, need_reviewer: bool) -> Actor:
        """Authenticate a Console request. Reviewer rights exist only for requests that prove the passphrase."""
        token = headers.get(OPERATOR_TOKEN_HEADER, "")
        if not token or not hmac.compare_digest(token.encode(), self.operator_token.encode()):
            raise BackendError("UNAUTHENTICATED", "a valid operator token is required")
        name = headers.get(ACTOR_HEADER, "")
        if not NAME_PATTERN.match(name):
            raise BackendError("UNAUTHENTICATED", f"{ACTOR_HEADER} must name the person acting")
        roles = {RESEARCHER}
        if need_reviewer:
            passphrase = headers.get(PASSPHRASE_HEADER, "")
            if not passphrase or not verify_passphrase(passphrase, self.reviewer_passphrase_hash):
                raise BackendError("PERMISSION_DENIED", "this action needs the reviewer passphrase")
            roles.add(REVIEWER)
        return Actor(name, frozenset(roles))


def bearer_token(headers: Mapping[str, str]) -> str:
    value = headers.get("Authorization", "")
    if not value.startswith("Bearer ") or len(value) <= 7:
        raise BackendError("UNAUTHENTICATED", "a bench bearer token is required")
    return value[7:].strip()
