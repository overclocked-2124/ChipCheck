"""Serial bench adapter (HLD 10 WP9): COBS+CRC framing, message set, MCU emulator, host adapter.

Modules: ``framing`` (HLD 05 §9.1), ``messages`` (§9.2 payload layouts, the firmware's wire spec),
``stream`` (byte-stream transport), ``mcu_emulator`` (reference implementation of the RP2040
firmware), ``host`` (``SerialBenchAdapter``). Standard library only; pyserial is imported lazily
by ``stream.PySerialStream``.
"""
