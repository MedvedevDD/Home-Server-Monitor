"""Decode the smartctl bit-mask exit status for diagnostic logging."""

from __future__ import annotations


class SmartExitDecoder:
    """Translate smartctl exit status bits into human-readable reasons."""

    _REASONS = {
        1: "Command line did not parse",
        2: "Device open failed or device did not return an identification response",
        4: "SMART command failed or checksum error occurred",
        8: "SMART overall-health self-assessment test failed",
        16: "SMART prefail attribute is below threshold",
        32: "SMART error log contains records",
        64: "Self-test log contains records",
        128: "SMART selective self-test log contains records",
    }

    @classmethod
    def decode(cls, exit_code: int) -> list[str]:
        """Return all reasons represented by a smartctl exit bit mask."""
        if exit_code <= 0:
            return []
        return [reason for bit, reason in cls._REASONS.items() if exit_code & bit]
