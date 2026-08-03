"""Storage status evaluation rules."""

from __future__ import annotations

from models.disk_health import DiskHealth
from models.storage_status import StorageStatus


STATUS_HEALTHY = "Healthy"
STATUS_WARNING = "Warning"
STATUS_CRITICAL = "Critical"
STATUS_UNKNOWN = "Unknown"

SCORE_BY_STATUS = {
    STATUS_HEALTHY: 100,
    STATUS_WARNING: 70,
    STATUS_CRITICAL: 30,
    STATUS_UNKNOWN: 50,
}


def evaluate_storage_status(health: DiskHealth | None) -> StorageStatus:
    """Evaluate a simple, deterministic status from one SMART result."""
    if health is None:
        return StorageStatus(
            status=STATUS_UNKNOWN,
            health_score=SCORE_BY_STATUS[STATUS_UNKNOWN],
            smart_available=False,
            smartctl_exit_code=None,
            health_passed=None,
            temperature_c=None,
            reallocated_sectors=None,
            pending_sectors=None,
            offline_uncorrectable=None,
            crc_errors=None,
        )

    status = _status_name(health)
    return StorageStatus(
        status=status,
        health_score=SCORE_BY_STATUS[status],
        smart_available=health.smart_available,
        smartctl_exit_code=health.smartctl_exit_code,
        health_passed=health.health_passed,
        temperature_c=health.temperature_c,
        reallocated_sectors=health.reallocated_sectors,
        pending_sectors=health.pending_sectors,
        offline_uncorrectable=health.offline_uncorrectable,
        crc_errors=health.crc_errors,
    )


def _status_name(health: DiskHealth) -> str:
    if not health.smart_available:
        return STATUS_UNKNOWN

    if health.health_passed is False:
        return STATUS_CRITICAL
    if _positive(health.pending_sectors):
        return STATUS_CRITICAL
    if _positive(health.offline_uncorrectable):
        return STATUS_CRITICAL
    if health.temperature_c is not None and health.temperature_c >= 55:
        return STATUS_CRITICAL

    if _positive(health.reallocated_sectors):
        return STATUS_WARNING
    if health.temperature_c is not None and health.temperature_c >= 45:
        return STATUS_WARNING
    if health.smartctl_exit_code != 0:
        return STATUS_WARNING

    return STATUS_HEALTHY


def _positive(value: int | None) -> bool:
    return value is not None and value > 0
