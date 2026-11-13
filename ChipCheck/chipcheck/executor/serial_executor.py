"""Future ESP32 Hardware Serial Executor Interface for ChipCheck.

This module defines the architectural interface for physical ESP32 hardware
execution over USB Serial, prepared so that the simulator can be dropped and
replaced without changing the adaptive planner, safety validator, or oracle.

Communication Protocol:
- Transport: USB Serial (CDC-ACM / UART) at configurable baud rate (default 115200)
- Protocol: Newline-delimited JSON (NDJSON)
- Framing: Each message ends with '\\n'

Input (PC -> ESP32):
  {"experiment_id": 101, "command": "RUN_TIMING_TEST", "parameters": {...}}\\n

Output (ESP32 -> PC):
  {"experiment_id": 101, "status": "COMPLETED", "results": {...}}\\n

Robustness & Fault Handling:
- Serial communication timeouts, malformed JSON, CRC/parity errors, and
  mismatched experiment IDs are classified as INVALID_EXPERIMENT or
  INCONCLUSIVE, NEVER as automatic DUT functional failures.
- Monotonic timestamps from the ESP32 hardware timer (esp_timer_get_time)
  are strictly used. PC arrival timestamps are NEVER used as replacements.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional, Any

from chipcheck.models import (
    ExperimentConfig, ExecutionResult, ExecutionStatus,
)
from chipcheck.executor import ExperimentExecutor

logger = logging.getLogger(__name__)


class ESP32SerialExecutor(ExperimentExecutor):
    """Executor for physical ESP32 hardware over USB Serial.

    Note: This is a designed hardware interface and stub. Real hardware
    communication is activated when a physical device is connected.
    """

    def __init__(
        self,
        port: str = "COM3",
        baudrate: int = 115200,
        timeout_seconds: float = 35.0,
        serial_device: Optional[Any] = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout_seconds = timeout_seconds
        self._serial = serial_device  # Can inject mock or pyserial object

    def get_name(self) -> str:
        return f"ESP32SerialExecutor(port={self.port}, baud={self.baudrate})"

    def close(self) -> None:
        """Close the connected serial device, if one was supplied."""
        if self._serial is not None and getattr(self._serial, "is_open", True):
            self._serial.close()

    def serialize_request(self, config: ExperimentConfig) -> str:
        """Serialize configuration to newline-delimited JSON."""
        msg = {
            "experiment_id": config.experiment_id,
            "command": config.command,
            "parameters": config.parameters,
        }
        return json.dumps(msg) + "\n"

    def parse_response(self, raw_line: str, expected_id: int) -> ExecutionResult:
        """Parse and validate output JSON from ESP32.

        Handles:
        - Malformed JSON -> ExecutionStatus.FAILED (treated by oracle as invalid)
        - Mismatched experiment_id -> ExecutionStatus.FAILED
        - Missing required fields -> ExecutionStatus.FAILED
        """
        try:
            data = json.loads(raw_line.strip())
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("ESP32 response malformed JSON: %s (raw: %r)", e, raw_line)
            return ExecutionResult(
                experiment_id=expected_id,
                status=ExecutionStatus.FAILED,
                results={"error": f"Malformed JSON: {e}"},
            )

        received_id = data.get("experiment_id")
        if received_id != expected_id:
            logger.error(
                "Mismatched experiment_id: expected %d, got %s",
                expected_id, received_id,
            )
            return ExecutionResult(
                experiment_id=expected_id,
                status=ExecutionStatus.FAILED,
                results={"error": f"Mismatched experiment_id (got {received_id})"},
            )

        status_str = data.get("status", "FAILED")
        try:
            status = ExecutionStatus(status_str)
        except ValueError:
            status = ExecutionStatus.FAILED

        results = data.get("results", {})
        return ExecutionResult(
            experiment_id=expected_id,
            status=status,
            results=results,
        )

    def execute(self, config: ExperimentConfig) -> ExecutionResult:
        """Execute experiment on hardware via USB Serial.

        If physical serial device is not connected, returns an informative
        INCONCLUSIVE/FAILED status.
        """
        if self._serial is None:
            # When physical hardware is not attached in simulation mode:
            logger.warning(
                "Physical hardware not connected on %s. Use ESP32TimingSimulator.",
                self.port,
            )
            return ExecutionResult(
                experiment_id=config.experiment_id,
                status=ExecutionStatus.FAILED,
                results={"error": f"No serial device connected on {self.port}"},
            )

        # Physical serial transaction:
        try:
            payload = self.serialize_request(config)
            self._serial.write(payload.encode("utf-8"))
            self._serial.flush()

            # Wait for response with timeout
            start_time = time.time()
            raw_response = ""
            while (time.time() - start_time) < self.timeout_seconds:
                if self._serial.in_waiting > 0:
                    raw_response = self._serial.readline().decode("utf-8")
                    if raw_response.strip():
                        break
                time.sleep(0.01)

            if not raw_response.strip():
                logger.error("ESP32 timed out on experiment %d", config.experiment_id)
                return ExecutionResult(
                    experiment_id=config.experiment_id,
                    status=ExecutionStatus.FAILED,
                    results={"error": "Hardware communication timeout"},
                )

            return self.parse_response(raw_response, config.experiment_id)

        except Exception as e:
            logger.error("Serial communication error: %s", e)
            return ExecutionResult(
                experiment_id=config.experiment_id,
                status=ExecutionStatus.FAILED,
                results={"error": f"Serial I/O exception: {e}"},
            )

