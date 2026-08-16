"""Rule-based infrastructure health evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Iterable

from core.manager import ProviderRun
from metric import Metric


class Severity(IntEnum):
    OK = 0
    WARNING = 1
    HIGH = 2
    CRITICAL = 3
    UNKNOWN = 4

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Finding:
    domain: str
    severity: Severity
    rule: str
    reason: str
    subject: str = ""
    impact: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "severity": self.severity.label,
            "rule": self.rule,
            "reason": self.reason,
            "subject": self.subject,
            "impact": self.impact,
        }


Predicate = Callable[[Metric], bool]
ReasonFactory = Callable[[Metric], str]
SubjectFactory = Callable[[Metric], str]


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    measurements: tuple[str, ...]
    severity: Severity
    when: Predicate
    reason: ReasonFactory
    subject: SubjectFactory = lambda metric: ""
    impact: int = 0

    def evaluate(self, metric: Metric, domain: str) -> Finding | None:
        if metric.measurement not in self.measurements or not self.when(metric):
            return None
        return Finding(
            domain=domain,
            severity=self.severity,
            rule=self.name,
            reason=self.reason(metric),
            subject=self.subject(metric),
            impact=self.impact,
        )


@dataclass(slots=True)
class DomainHealth:
    name: str
    severity: Severity = Severity.OK
    score: int = 100
    findings: list[Finding] = field(default_factory=list)
    metric_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.severity.label,
            "score": self.score,
            "metric_count": self.metric_count,
            "findings": [item.as_dict() for item in self.findings],
        }


@dataclass(slots=True)
class HealthSummary:
    score: int
    status: str
    warnings: int
    errors: int
    domains: list[DomainHealth] = field(default_factory=list)
    primary_finding: Finding | None = None
    warning_count: int = 0
    high_count: int = 0
    critical_count: int = 0
    unknown_count: int = 0

    @property
    def severity(self) -> Severity:
        try:
            return Severity[self.status.upper()]
        except KeyError:
            return Severity.UNKNOWN

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.upper(),
            "score": self.score,
            "warnings": self.warnings,
            "errors": self.errors,
            "counts": {
                "warning": self.warning_count,
                "high": self.high_count,
                "critical": self.critical_count,
                "unknown": self.unknown_count,
            },
            "primary_finding": self.primary_finding.as_dict() if self.primary_finding else None,
            "domains": [domain.as_dict() for domain in self.domains],
        }


def _field(metric: Metric, name: str, default: object = None) -> object:
    return metric.fields.get(name, default)


def _number(metric: Metric, name: str, default: float = 0.0) -> float:
    value = _field(metric, name, default)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _tag(metric: Metric, name: str, default: str = "") -> str:
    value = metric.tags.get(name, default)
    return str(value)


def _device(metric: Metric) -> str:
    return _tag(metric, "device") or _tag(metric, "serial")


def _storage_name(metric: Metric) -> str:
    return _tag(metric, "storage")


def _raid_subject(metric: Metric) -> str:
    if metric.measurement == "raid_controller_status":
        return f"controller {_tag(metric, 'controller')}"
    if metric.measurement == "raid_array_status":
        return f"array {_tag(metric, 'array_id')}"
    return f"drive {_tag(metric, 'drive_id')}"


def _has_number(metric: Metric, name: str) -> bool:
    value = _field(metric, name)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _raid_state(metric: Metric) -> str:
    return str(_field(metric, "status", _field(metric, "state", "unknown")))


def _ups_name(metric: Metric) -> str:
    return _tag(metric, "ups_name") or _tag(metric, "host")


def _node(metric: Metric) -> str:
    return _tag(metric, "node") or _tag(metric, "host")


def _load_ratio(metric: Metric, field: str) -> float:
    cpus = max(1.0, _number(metric, "cpu_count", 1.0))
    return _number(metric, field) / cpus


STORAGE_RULES = (
    Rule("smart-failed", ("storage_health",), Severity.CRITICAL,
         lambda m: _field(m, "health_passed") is False,
         lambda m: "SMART overall-health result is FAILED", _device, 60),
    Rule("offline-uncorrectable", ("storage_health",), Severity.CRITICAL,
         lambda m: _number(m, "offline_uncorrectable") > 0,
         lambda m: f"offline uncorrectable sectors: {int(_number(m, 'offline_uncorrectable'))}", _device, 60),
    Rule("pending-sectors", ("storage_health",), Severity.HIGH,
         lambda m: _number(m, "pending_sectors") > 0,
         lambda m: f"pending sectors: {int(_number(m, 'pending_sectors'))}", _device, 25),
    Rule("reallocated-sectors", ("storage_health",), Severity.WARNING,
         lambda m: _number(m, "reallocated_sectors") > 0,
         lambda m: f"reallocated sectors: {int(_number(m, 'reallocated_sectors'))}", _device, 10),
    Rule("disk-temperature-critical", ("storage_health",), Severity.CRITICAL,
         lambda m: _has_number(m, "temperature_c") and _number(m, "temperature_c") >= 60,
         lambda m: f"disk temperature is {_number(m, 'temperature_c'):.0f} C", _device, 40),
    Rule("disk-temperature-high", ("storage_health",), Severity.HIGH,
         lambda m: _has_number(m, "temperature_c") and 55 <= _number(m, "temperature_c") < 60,
         lambda m: f"disk temperature is {_number(m, 'temperature_c'):.0f} C", _device, 20),
    Rule("disk-temperature-warning", ("storage_health",), Severity.WARNING,
         lambda m: _has_number(m, "temperature_c") and 45 <= _number(m, "temperature_c") < 55,
         lambda m: f"disk temperature is {_number(m, 'temperature_c'):.0f} C", _device, 5),
    Rule("smart-error-log", ("storage_health",), Severity.WARNING,
         lambda m: int(_number(m, "smartctl_exit_code")) & 32 != 0,
         lambda m: "SMART error log contains records", _device, 5),
    Rule("smart-self-test-log", ("storage_health",), Severity.WARNING,
         lambda m: int(_number(m, "smartctl_exit_code")) & 64 != 0,
         lambda m: "SMART self-test log contains records", _device, 5),
    Rule("smart-command-error", ("storage_health",), Severity.UNKNOWN,
         lambda m: int(_number(m, "smartctl_exit_code")) & 3 != 0,
         lambda m: f"smartctl could not fully access the device (exit code {int(_number(m, 'smartctl_exit_code'))})", _device, 15),
    Rule("smart-unavailable", ("storage_health",), Severity.UNKNOWN,
         lambda m: _field(m, "smart_available") is False,
         lambda m: "SMART data is unavailable", _device, 15),
)

RAID_RULES = (
    Rule("raid-critical", ("raid_controller_status", "raid_array_status", "raid_drive_status"), Severity.CRITICAL,
         lambda m: _number(m, "status_code") >= 3,
         lambda m: f"RAID state is {_raid_state(m)}", _raid_subject, 40),
    Rule("raid-operation", ("raid_controller_status", "raid_array_status", "raid_drive_status"), Severity.WARNING,
         lambda m: _number(m, "status_code") == 2,
         lambda m: f"RAID state is {_raid_state(m)}", _raid_subject, 5),
    Rule("raid-unknown", ("raid_controller_status", "raid_array_status", "raid_drive_status"), Severity.UNKNOWN,
         lambda m: _number(m, "status_code") == 0,
         lambda m: f"RAID state is {_raid_state(m)}", _raid_subject, 15),
    Rule("raid-media-errors", ("raid_drive_status",), Severity.HIGH,
         lambda m: _number(m, "media_errors") > 0,
         lambda m: f"media errors: {int(_number(m, 'media_errors'))}", _raid_subject, 25),
    Rule("raid-predictive-failure", ("raid_drive_status",), Severity.CRITICAL,
         lambda m: _number(m, "predictive_failures") > 0,
         lambda m: f"predictive failure count: {int(_number(m, 'predictive_failures'))}", _raid_subject, 60),
    Rule("raid-other-errors", ("raid_drive_status",), Severity.WARNING,
         lambda m: _number(m, "other_errors") > 0,
         lambda m: f"other drive errors: {int(_number(m, 'other_errors'))}", _raid_subject, 10),
    Rule("raid-drive-temperature-critical", ("raid_drive_status",), Severity.CRITICAL,
         lambda m: _has_number(m, "temperature_c") and _number(m, "temperature_c") >= 60,
         lambda m: f"drive temperature is {_number(m, 'temperature_c'):.0f} C", _raid_subject, 40),
    Rule("raid-drive-temperature-high", ("raid_drive_status",), Severity.HIGH,
         lambda m: _has_number(m, "temperature_c") and 55 <= _number(m, "temperature_c") < 60,
         lambda m: f"drive temperature is {_number(m, 'temperature_c'):.0f} C", _raid_subject, 20),
    Rule("raid-drive-temperature-warning", ("raid_drive_status",), Severity.WARNING,
         lambda m: _has_number(m, "temperature_c") and 45 <= _number(m, "temperature_c") < 55,
         lambda m: f"drive temperature is {_number(m, 'temperature_c'):.0f} C", _raid_subject, 5),
)

UPS_RULES = (
    Rule("ups-low-battery", ("ups_status",), Severity.CRITICAL,
         lambda m: bool(_field(m, "low_battery", False)), lambda m: "UPS reports low battery", _ups_name, 60),
    Rule("ups-overload", ("ups_status",), Severity.CRITICAL,
         lambda m: bool(_field(m, "overload", False)), lambda m: "UPS reports overload", _ups_name, 60),
    Rule("ups-replace-battery", ("ups_status",), Severity.HIGH,
         lambda m: bool(_field(m, "replace_battery", False)), lambda m: "UPS reports that the battery must be replaced", _ups_name, 25),
    Rule("ups-on-battery", ("ups_status",), Severity.HIGH,
         lambda m: bool(_field(m, "on_battery", False)), lambda m: "UPS is running on battery", _ups_name, 20),
    Rule("ups-offline", ("ups_status",), Severity.CRITICAL,
         lambda m: _field(m, "online") is False and not bool(_field(m, "on_battery", False)),
         lambda m: "UPS is neither online nor running on battery", _ups_name, 60),
    Rule("ups-battery-critical", ("ups_status",), Severity.CRITICAL,
         lambda m: _has_number(m, "battery_charge_estimated") and _number(m, "battery_charge_estimated") < 20,
         lambda m: f"estimated battery charge is {_number(m, 'battery_charge_estimated'):.0f}%", _ups_name, 40),
    Rule("ups-battery-high", ("ups_status",), Severity.HIGH,
         lambda m: _has_number(m, "battery_charge_estimated") and 20 <= _number(m, "battery_charge_estimated") < 35,
         lambda m: f"estimated battery charge is {_number(m, 'battery_charge_estimated'):.0f}%", _ups_name, 20),
    Rule("ups-battery-warning", ("ups_status",), Severity.WARNING,
         lambda m: _has_number(m, "battery_charge_estimated") and 35 <= _number(m, "battery_charge_estimated") < 50,
         lambda m: f"estimated battery charge is {_number(m, 'battery_charge_estimated'):.0f}%", _ups_name, 5),
    Rule("ups-load-critical", ("ups_status",), Severity.CRITICAL,
         lambda m: _has_number(m, "load_percent") and _number(m, "load_percent") >= 100,
         lambda m: f"UPS load is {_number(m, 'load_percent'):.0f}%", _ups_name, 40),
    Rule("ups-load-high", ("ups_status",), Severity.HIGH,
         lambda m: _has_number(m, "load_percent") and 90 <= _number(m, "load_percent") < 100,
         lambda m: f"UPS load is {_number(m, 'load_percent'):.0f}%", _ups_name, 20),
    Rule("ups-load-warning", ("ups_status",), Severity.WARNING,
         lambda m: _has_number(m, "load_percent") and 80 <= _number(m, "load_percent") < 90,
         lambda m: f"UPS load is {_number(m, 'load_percent'):.0f}%", _ups_name, 5),
    Rule("ups-temperature-critical", ("ups_status",), Severity.CRITICAL,
         lambda m: _has_number(m, "internal_temp") and _number(m, "internal_temp") >= 60,
         lambda m: f"UPS internal temperature is {_number(m, 'internal_temp'):.0f} C", _ups_name, 40),
    Rule("ups-temperature-high", ("ups_status",), Severity.HIGH,
         lambda m: _has_number(m, "internal_temp") and 55 <= _number(m, "internal_temp") < 60,
         lambda m: f"UPS internal temperature is {_number(m, 'internal_temp'):.0f} C", _ups_name, 20),
    Rule("ups-temperature-warning", ("ups_status",), Severity.WARNING,
         lambda m: _has_number(m, "internal_temp") and 50 <= _number(m, "internal_temp") < 55,
         lambda m: f"UPS internal temperature is {_number(m, 'internal_temp'):.0f} C", _ups_name, 5),
)

PROXMOX_RULES = (
    Rule("proxmox-storage-inactive", ("proxmox_storage",), Severity.CRITICAL,
         lambda m: _field(m, "enabled") is True and _field(m, "active") is False,
         lambda m: "enabled Proxmox storage is inactive", _storage_name, 60),
    Rule("proxmox-storage-critical", ("proxmox_storage",), Severity.CRITICAL,
         lambda m: _field(m, "active") is not False and (_number(m, "used_percent") >= 97 or _number(m, "health_code") >= 3),
         lambda m: f"storage usage is {_number(m, 'used_percent'):.2f}%", _storage_name, 40),
    Rule("proxmox-storage-high", ("proxmox_storage",), Severity.HIGH,
         lambda m: _field(m, "active") is not False and 90 <= _number(m, "used_percent") < 97,
         lambda m: f"storage usage is {_number(m, 'used_percent'):.2f}%", _storage_name, 20),
    Rule("proxmox-storage-warning", ("proxmox_storage",), Severity.WARNING,
         lambda m: _field(m, "active") is not False and 80 <= _number(m, "used_percent") < 90,
         lambda m: f"storage usage is {_number(m, 'used_percent'):.2f}%", _storage_name, 5),
    Rule("memory-critical", ("proxmox_host_status",), Severity.CRITICAL,
         lambda m: _number(m, "memory_used_percent") >= 98,
         lambda m: f"memory usage is {_number(m, 'memory_used_percent'):.2f}%", _node, 40),
    Rule("memory-high", ("proxmox_host_status",), Severity.HIGH,
         lambda m: 95 <= _number(m, "memory_used_percent") < 98,
         lambda m: f"memory usage is {_number(m, 'memory_used_percent'):.2f}%", _node, 20),
    Rule("memory-warning", ("proxmox_host_status",), Severity.WARNING,
         lambda m: 90 <= _number(m, "memory_used_percent") < 95,
         lambda m: f"memory usage is {_number(m, 'memory_used_percent'):.2f}%", _node, 5),
    Rule("swap-critical", ("proxmox_host_status",), Severity.CRITICAL,
         lambda m: _number(m, "swap_total_bytes") > 0 and _number(m, "swap_used_percent") >= 90,
         lambda m: f"swap usage is {_number(m, 'swap_used_percent'):.2f}%", _node, 40),
    Rule("swap-high", ("proxmox_host_status",), Severity.HIGH,
         lambda m: _number(m, "swap_total_bytes") > 0 and 75 <= _number(m, "swap_used_percent") < 90,
         lambda m: f"swap usage is {_number(m, 'swap_used_percent'):.2f}%", _node, 20),
    Rule("swap-warning", ("proxmox_host_status",), Severity.WARNING,
         lambda m: _number(m, "swap_total_bytes") > 0 and 50 <= _number(m, "swap_used_percent") < 75,
         lambda m: f"swap usage is {_number(m, 'swap_used_percent'):.2f}%", _node, 5),
    Rule("cpu-critical", ("proxmox_host_status",), Severity.CRITICAL,
         lambda m: _number(m, "cpu_usage_percent") >= 98,
         lambda m: f"CPU usage is {_number(m, 'cpu_usage_percent'):.2f}%", _node, 40),
    Rule("cpu-high", ("proxmox_host_status",), Severity.HIGH,
         lambda m: 95 <= _number(m, "cpu_usage_percent") < 98,
         lambda m: f"CPU usage is {_number(m, 'cpu_usage_percent'):.2f}%", _node, 20),
    Rule("load-critical", ("proxmox_host_status",), Severity.CRITICAL,
         lambda m: _load_ratio(m, "load15") >= 2.0,
         lambda m: f"15-minute load is {_number(m, 'load15'):.2f} for {int(_number(m, 'cpu_count', 1))} CPUs", _node, 40),
    Rule("load-high", ("proxmox_host_status",), Severity.HIGH,
         lambda m: 1.5 <= _load_ratio(m, "load15") < 2.0,
         lambda m: f"15-minute load is {_number(m, 'load15'):.2f} for {int(_number(m, 'cpu_count', 1))} CPUs", _node, 20),
    Rule("load-warning", ("proxmox_host_status",), Severity.WARNING,
         lambda m: 1.0 <= _load_ratio(m, "load15") < 1.5,
         lambda m: f"15-minute load is {_number(m, 'load15'):.2f} for {int(_number(m, 'cpu_count', 1))} CPUs", _node, 5),
)

COOLING_RULES = (
    Rule(
        "cooling-control-unverified",
        ("cooling_status",),
        Severity.WARNING,
        lambda m: _field(m, "hardware_access_ok") is False
        and _field(m, "bmc_all_sensors_na") is not True,
        lambda m: "x8fan/W83795 access is unavailable; fan control cannot be verified",
        lambda m: _tag(m, "controller") or "W83795ADG",
        15,
    ),
    Rule(
        "cooling-control-critical",
        ("cooling_status",),
        Severity.CRITICAL,
        lambda m: _field(m, "hardware_access_ok") is False
        and _field(m, "bmc_all_sensors_na") is True,
        lambda m: "W83795 access is lost and all BMC sensors are N/A; fan control cannot be verified",
        lambda m: _tag(m, "controller") or "W83795ADG",
        60,
    ),
)

RULES_BY_DOMAIN = {
    "storage": STORAGE_RULES,
    "raid": RAID_RULES,
    "ups": UPS_RULES,
    "proxmox": PROXMOX_RULES,
    "cooling": COOLING_RULES,
}

DOMAIN_ORDER = ("storage", "raid", "ups", "proxmox", "cooling")


def _finding_sort_key(item: Finding) -> tuple[int, int, str, str]:
    return (-item.impact, -int(item.severity), item.domain, item.subject)

def _domain_health(run: ProviderRun) -> DomainHealth:
    name = run.provider.name
    domain = DomainHealth(name=name)

    if not run.discovery.ready:
        domain.findings.append(Finding(name, Severity.UNKNOWN, "collector-unavailable", run.discovery.detail or "collector is unavailable", impact=25))
    elif run.result is None:
        domain.findings.append(Finding(name, Severity.UNKNOWN, "no-result", "collector returned no result", impact=25))
    else:
        domain.metric_count = len(run.result.metrics)
        for message in run.result.warnings:
            domain.findings.append(Finding(name, Severity.WARNING, "collector-warning", message.message, impact=5))
        for message in run.result.errors:
            domain.findings.append(Finding(name, Severity.UNKNOWN, "collector-error", message.message, impact=25))
        for metric in run.result.metrics:
            for rule in RULES_BY_DOMAIN.get(name, ()):
                finding = rule.evaluate(metric, name)
                if finding is not None:
                    domain.findings.append(finding)

    if domain.findings:
        domain.severity = max((item.severity for item in domain.findings), key=int)
        domain.findings.sort(key=_finding_sort_key)
        domain.score = max(0, 100 - sum(item.impact for item in domain.findings))
    return domain


def summarize_health(runs: Iterable[ProviderRun]) -> HealthSummary:
    domains = [_domain_health(run) for run in runs]
    domains.sort(key=lambda item: (DOMAIN_ORDER.index(item.name) if item.name in DOMAIN_ORDER else len(DOMAIN_ORDER), item.name))
    if not domains:
        return HealthSummary(score=0, status="unknown", warnings=0, errors=1, domains=[], unknown_count=1)

    findings = [item for domain in domains for item in domain.findings]
    findings.sort(key=_finding_sort_key)
    severity = max((domain.severity for domain in domains), key=int)
    score = max(0, 100 - sum(item.impact for item in findings))
    warning_count = sum(item.severity == Severity.WARNING for item in findings)
    high_count = sum(item.severity == Severity.HIGH for item in findings)
    critical_count = sum(item.severity == Severity.CRITICAL for item in findings)
    unknown_count = sum(item.severity == Severity.UNKNOWN for item in findings)
    errors = high_count + critical_count + unknown_count
    return HealthSummary(
        score=score,
        status=severity.label.lower(),
        warnings=warning_count,
        errors=errors,
        domains=domains,
        primary_finding=findings[0] if findings else None,
        warning_count=warning_count,
        high_count=high_count,
        critical_count=critical_count,
        unknown_count=unknown_count,
    )
