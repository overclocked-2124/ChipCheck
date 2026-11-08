"""Safety-rule library shared by Backend (authoritative validation) and Controller (bench re-check).

Pure Python, deterministic, fail closed (HLD 03 §11, HLD 10 §4).
"""

from activequal.model.safety.live import LiveReadings, capture_trips, live_trips
from activequal.model.safety.rules import (CODES, SHUTDOWN_ALLOWANCE_S, SafetyDecision, Violation,
                                           check_candidate)

__all__ = ["CODES", "SHUTDOWN_ALLOWANCE_S", "LiveReadings", "SafetyDecision", "Violation", "capture_trips",
           "check_candidate", "live_trips"]
