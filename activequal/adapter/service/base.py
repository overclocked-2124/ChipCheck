"""The ``BenchAdapter`` boundary (SWE-POC-HANDOFF §6.1, HLD 03 §10).

Everything above the Adapter must not know whether it talks to the simulator or to serial
ports. The interface has no way to ask about, or return, the seeded fault.
"""

from __future__ import annotations

from typing import Protocol

from activequal.adapter.service.types import ApprovedEpisode, BenchHealth, RawBenchCapture


class BenchAdapter(Protocol):
    def health_check(self) -> BenchHealth:
        """Verify the test-controller watchdog, E-stop and lockout state, and DUT and instrument links."""
        ...

    def apply_and_measure(self, episode: ApprovedEpisode) -> RawBenchCapture:
        """Run PREFLIGHT through ordered shutdown and return what the bench captured.

        Applies rails and discrete states, runs the workload, observes, then shuts down.
        On any fault it returns the capture a real bench would produce (trip set, shutdown not
        confirmed, missing observations listed); it never returns a fabricated success.
        """
        ...

    def emergency_shutdown(self) -> None:
        """Immediately de-energise all programmable rails (hardware cutoff path)."""
        ...
