"""Byte-stream transport (HLD 10 §5.3: no OS-specific test transport).

Adapters talk to a ``ByteStream``. Tests use ``InMemoryPipe`` (and the emulator's loopback), real
benches use ``PySerialStream``. pyserial is imported lazily and is never a hard dependency.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Protocol


class StreamClosed(OSError):
    """The stream is closed or the device disappeared."""


class ByteStream(Protocol):
    def write(self, data: bytes) -> None: ...

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        """Return up to ``max_bytes`` bytes, waiting at most ``timeout_s``; ``b""`` means nothing arrived."""
        ...

    def close(self) -> None: ...


class _Endpoint:
    def __init__(self) -> None:
        self.peer: _Endpoint | None = None
        self._inbox: deque[int] = deque()
        self.closed = False
        # Called as on_idle(timeout_s) when a read finds nothing: lets a virtual clock advance.
        self.on_idle: Callable[[float], None] | None = None
        self.on_write: Callable[[], None] | None = None

    def write(self, data: bytes) -> None:
        if self.closed or self.peer is None or self.peer.closed:
            raise StreamClosed("pipe closed")
        self.peer._inbox.extend(data)
        if self.peer.on_write is not None:
            self.peer.on_write()

    def read(self, max_bytes: int, timeout_s: float = 0.0) -> bytes:
        if self.closed:
            raise StreamClosed("pipe closed")
        if not self._inbox and self.on_idle is not None and timeout_s > 0:
            self.on_idle(timeout_s)
        count = min(max_bytes, len(self._inbox))
        return bytes(self._inbox.popleft() for _ in range(count))

    def pending(self) -> int:
        return len(self._inbox)

    def close(self) -> None:
        self.closed = True


class InMemoryPipe:
    """A connected pair of byte streams: ``a`` and ``b``. Whatever one writes the other reads."""

    def __init__(self) -> None:
        self.a, self.b = _Endpoint(), _Endpoint()
        self.a.peer, self.b.peer = self.b, self.a


class PySerialStream:
    """``ByteStream`` over a pyserial port. ``serial`` is imported here, never at module import."""

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        try:
            import serial                                  # noqa: PLC0415 (deliberately lazy)
        except ImportError as exc:
            raise RuntimeError("pyserial is required for real serial ports: pip install pyserial") from exc
        self._serial = serial.Serial(port, baudrate=baudrate, timeout=0, write_timeout=1.0)

    def write(self, data: bytes) -> None:
        try:
            self._serial.write(data)
            self._serial.flush()
        except Exception as exc:                            # serial.SerialException and OSError
            raise StreamClosed(str(exc)) from exc

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        try:
            self._serial.timeout = max(0.0, timeout_s)
            first = self._serial.read(1)
            if not first:
                return b""
            waiting = min(max_bytes - 1, self._serial.in_waiting)
            return first + (self._serial.read(waiting) if waiting > 0 else b"")
        except Exception as exc:
            raise StreamClosed(str(exc)) from exc

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass
