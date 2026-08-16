"""Home Server Monitor command-line entry point."""

from __future__ import annotations

import logging

import config
import sys
from collections.abc import Iterable

from collectors.storage import StorageCollector
from collectors.ups import UPSCollectionError, UPSCollector
from models.raid import RaidArrayStatus, RaidControllerStatus, RaidDriveStatus
from services.raid_collectors import RaidCollectionError, RaidCollector
from exceptions import CollectorError
from metric import Metric
from models.disk import Disk
from models.disk_health import DiskHealth
from models.storage_status import StorageStatus
from models.ups_status import UPSStatus
from services.smart import SmartService, SmartctlUnavailableError
from services.raid_discovery import RaidDiscoveryResult, RaidDiscoveryService
from services.storage_status import evaluate_storage_status
from core.registry import ProviderRegistry
from core.pipeline import MetricsPipeline
from providers.storage import StorageProvider
from providers.ups import UPSProvider
from providers.raid import RaidProvider
from providers.proxmox import ProxmoxProvider
from services.proxmox_host import ProxmoxHostCollector
from services.proxmox_storage import ProxmoxStorageCollector
from models.proxmox_storage import ProxmoxStorageStatus
from models.proxmox_host import ProxmoxHostStatus
from models.cooling import CoolingStatus
from providers.cooling import CoolingProvider
from services.cooling import CoolingCollector


LOGGER = logging.getLogger("home_server_monitor.collector")
INVENTORY_MEASUREMENT = "storage_inventory"
HEALTH_MEASUREMENT = "storage_health"
STATUS_MEASUREMENT = "storage_status"
UPS_STATUS_MEASUREMENT = "ups_status"
RAID_CONTROLLER_MEASUREMENT = "raid_controller_status"
RAID_ARRAY_MEASUREMENT = "raid_array_status"
RAID_DRIVE_MEASUREMENT = "raid_drive_status"
PROXMOX_HOST_INFO_MEASUREMENT = "proxmox_host_info"
PROXMOX_HOST_STATUS_MEASUREMENT = "proxmox_host_status"
PROXMOX_STORAGE_MEASUREMENT = "proxmox_storage"
COOLING_STATUS_MEASUREMENT = "cooling_status"
COOLING_FAN_MEASUREMENT = "cooling_fan"


def _stable_serial(disk: Disk) -> str:
    """Return the inventory serial or a deterministic device fallback."""
    serial = disk.serial.strip()
    if serial:
        return serial

    serial = disk.device.strip() or "unknown-device"
    LOGGER.warning(
        "Disk %s has no serial number; using %s as the stable identifier fallback",
        disk.device or disk.model or "unknown",
        serial,
    )
    return serial


def disk_to_metric(disk: Disk) -> Metric:
    """Convert one disk inventory object to an Influx Line Protocol metric."""
    return Metric(
        measurement=INVENTORY_MEASUREMENT,
        tags={
            "serial": _stable_serial(disk),
            "vendor": disk.vendor,
            "model": disk.model,
            "display_name": disk.display_name,
            "disk_type": disk.disk_type,
            "transport": disk.transport,
            "device": disk.device,
        },
        fields={
            "capacity_bytes": disk.capacity_bytes,
            "present": True,
        },
    )


def disk_health_to_metric(disk: Disk, health: DiskHealth) -> Metric:
    """Convert one SMART collection result to a storage_health metric."""
    fields: dict[str, bool | int] = {
        "smart_available": health.smart_available,
        "smartctl_exit_code": health.smartctl_exit_code,
    }

    optional_fields: dict[str, bool | int | None] = {
        "health_passed": health.health_passed,
        "temperature_c": health.temperature_c,
        "reallocated_sectors": health.reallocated_sectors,
        "pending_sectors": health.pending_sectors,
        "offline_uncorrectable": health.offline_uncorrectable,
        "crc_errors": health.crc_errors,
    }
    fields.update(
        {
            name: value
            for name, value in optional_fields.items()
            if value is not None
        }
    )

    return Metric(
        measurement=HEALTH_MEASUREMENT,
        tags={
            "serial": health.serial.strip() or _stable_serial(disk),
            "device": disk.device,
            "vendor": disk.vendor,
            "model": disk.model,
            "display_name": disk.display_name,
            "disk_type": disk.disk_type,
            "transport": disk.transport,
        },
        fields=fields,
    )



def disk_status_to_metric(disk: Disk, status: StorageStatus) -> Metric:
    """Convert combined inventory and health state to storage_status."""
    fields: dict[str, bool | int] = {
        "capacity_bytes": disk.capacity_bytes,
        "present": True,
        "smart_available": status.smart_available,
        "health_score": status.health_score,
        "status_code": {"Unknown": 0, "Healthy": 1, "Warning": 2, "Critical": 3}.get(status.status, 0),
    }

    optional_fields: dict[str, bool | int | None] = {
        "smartctl_exit_code": status.smartctl_exit_code,
        "health_passed": status.health_passed,
        "temperature_c": status.temperature_c,
        "reallocated_sectors": status.reallocated_sectors,
        "pending_sectors": status.pending_sectors,
        "offline_uncorrectable": status.offline_uncorrectable,
        "crc_errors": status.crc_errors,
    }
    fields.update(
        {
            name: value
            for name, value in optional_fields.items()
            if value is not None
        }
    )

    return Metric(
        measurement=STATUS_MEASUREMENT,
        tags={
            "serial": _stable_serial(disk),
            "vendor": disk.vendor,
            "model": disk.model,
            "display_name": disk.display_name,
            "disk_type": disk.disk_type,
            "transport": disk.transport,
            "device": disk.device,
        },
        fields=fields,
    )


def build_metrics(disks: Iterable[Disk]) -> list[Metric]:
    """Convert disk inventory into serializable metrics."""
    return [disk_to_metric(disk) for disk in disks]


def build_health_metrics(
    disks: Iterable[Disk],
    health_results: Iterable[DiskHealth],
) -> list[Metric]:
    """Join SMART results to inventory, preferring physical serial identity."""
    disk_list = list(disks)
    disks_by_device = {disk.device: disk for disk in disk_list if disk.device}
    disks_by_serial = {disk.serial.strip(): disk for disk in disk_list if disk.serial.strip()}
    metrics: list[Metric] = []

    for health in health_results:
        serial = health.serial.strip()
        disk = disks_by_serial.get(serial) if serial else None
        if disk is None:
            disk = disks_by_device.get(health.device)
        if disk is None:
            LOGGER.warning(
                "Ignoring SMART result for unknown inventory device %s",
                health.device,
            )
            continue
        metrics.append(disk_health_to_metric(disk, health))

    return metrics



def build_status_metrics(
    disks: Iterable[Disk],
    health_results: Iterable[DiskHealth],
) -> list[Metric]:
    """Build one combined status metric for every inventory disk."""
    disk_list = list(disks)
    disks_by_serial = {
        disk.serial.strip(): disk
        for disk in disk_list
        if disk.serial.strip()
    }
    disks_by_device = {
        disk.device: disk
        for disk in disk_list
        if disk.device
    }
    health_by_disk_id: dict[int, DiskHealth] = {}

    for health in health_results:
        serial = health.serial.strip()
        disk = disks_by_serial.get(serial) if serial else None
        if disk is None:
            disk = disks_by_device.get(health.device)
        if disk is not None:
            health_by_disk_id[id(disk)] = health

    metrics: list[Metric] = []
    for disk in disk_list:
        health = health_by_disk_id.get(id(disk))
        metrics.append(disk_status_to_metric(disk, evaluate_storage_status(health)))

    return metrics




def storage_visible_disks(
    disks: Iterable[Disk],
    health_results: Iterable[DiskHealth],
    discovery: RaidDiscoveryResult | None = None,
) -> list[Disk]:
    """Return only disks that belong to the OS-visible Storage layer.

    Physical drives behind MegaRAID are intentionally excluded from every
    ``storage_*`` measurement. They are represented exclusively by the RAID
    measurements. StorCLI does not always expose an OS device or serial for
    JBOD disks, so the final identity set also uses SMART results collected
    through each controller control device.
    """
    disk_list = list(disks)
    health_list = list(health_results)

    controllers = list(discovery.megaraid_controllers) if discovery is not None else []
    control_devices = {
        controller.control_device
        for controller in controllers
        if controller.control_device
    }
    raid_os_devices = {
        drive.os_device.strip()
        for controller in controllers
        for drive in controller.drives
        if drive.os_device.strip()
    }
    raid_serials = {
        drive.serial.strip()
        for controller in controllers
        for drive in controller.drives
        if drive.serial.strip()
    }

    # MegaRaidProvider reports every physical drive through the controller's
    # control device. Its SMART serial is the most reliable identity when
    # StorCLI omits SN and OS Drive Name fields.
    raid_serials.update(
        health.serial.strip()
        for health in health_list
        if health.serial.strip()
        and (health.device in control_devices or discovery is None)
    )

    return [
        disk
        for disk in disk_list
        if disk.device not in raid_os_devices
        and (not disk.serial.strip() or disk.serial.strip() not in raid_serials)
    ]



def storage_visible_health_results(
    disks: Iterable[Disk],
    health_results: Iterable[DiskHealth],
) -> list[DiskHealth]:
    """Return SMART results that belong to visible Storage inventory disks."""
    disk_list = list(disks)
    serials = {disk.serial.strip() for disk in disk_list if disk.serial.strip()}
    devices = {disk.device for disk in disk_list if disk.device}
    return [
        health
        for health in health_results
        if (health.serial.strip() and health.serial.strip() in serials)
        or health.device in devices
    ]

def ups_status_to_metric(status: UPSStatus) -> Metric:
    """Convert normalized UPS state to a Grafana-friendly snapshot metric."""
    fields: dict[str, bool | int | float | str] = {
        "online": status.online,
        "on_battery": status.on_battery,
        "low_battery": status.low_battery,
        "overload": status.overload,
        "charging": status.charging,
        "discharging": status.discharging,
        "replace_battery": status.replace_battery,
        "raw_status": status.raw_status or "unknown",
        "status_code": status.status_code,
        "online_code": int(status.online),
        "on_battery_code": int(status.on_battery),
        "low_battery_code": int(status.low_battery),
    }
    optional_fields: dict[str, bool | int | float | None] = {
        "battery_voltage": status.battery_voltage,
        "battery_charge_estimated": status.battery_charge_estimated,
        "input_voltage": status.input_voltage,
        "output_voltage": status.output_voltage,
        "input_frequency": status.input_frequency,
        "load_percent": status.load_percent,
        "internal_temp": status.internal_temp,
        "beeper_enabled": status.beeper_enabled,
        "delay_start_seconds": status.delay_start_seconds,
        "delay_shutdown_seconds": status.delay_shutdown_seconds,
    }
    fields.update({name: value for name, value in optional_fields.items() if value is not None})
    return Metric(
        measurement=UPS_STATUS_MEASUREMENT,
        tags={
            "host": status.host,
            "ups_name": status.ups_name,
            "model": status.model or "unknown",
            "serial": status.serial or "unknown",
            "status": status.status,
        },
        fields=fields,
    )


def raid_controller_to_metric(item: RaidControllerStatus) -> Metric:
    fields: dict[str, bool | int | float | str] = {
        "present": True,
        "status_code": item.status_code,
        "health_score": item.health_score,
        "virtual_drive_count": item.virtual_drive_count,
        "physical_drive_count": item.physical_drive_count,
        "jbod_mode": item.jbod_mode,
    }
    optional = {
        "temperature_c": item.temperature_c,
        "cache_status": item.cache_status or None,
        "battery_status": item.battery_status or None,
        "patrol_read_status": item.patrol_read_status or None,
    }
    fields.update({k: v for k, v in optional.items() if v is not None})
    return Metric(
        measurement=RAID_CONTROLLER_MEASUREMENT,
        tags={
            "provider": item.provider,
            "controller": item.controller,
            "model": item.model or "unknown",
            "serial": item.serial or "unknown",
            "firmware": item.firmware or "unknown",
        },
        fields=fields,
    )


def raid_array_to_metric(item: RaidArrayStatus) -> Metric:
    fields: dict[str, bool | int | float | str] = {
        "present": True,
        "status_code": item.status_code,
        "health_score": item.health_score,
    }
    optional = {
        "size_bytes": item.size_bytes,
        "progress_percent": item.progress_percent,
        "operation": item.operation or None,
    }
    fields.update({k: v for k, v in optional.items() if v is not None})
    return Metric(
        measurement=RAID_ARRAY_MEASUREMENT,
        tags={
            "provider": item.provider,
            "controller": item.controller,
            "array_id": item.array_id,
            "name": item.name or "unnamed",
            "raid_level": item.raid_level or "unknown",
        },
        fields=fields,
    )


def raid_drive_to_metric(item: RaidDriveStatus) -> Metric:
    fields: dict[str, bool | int | float | str] = {
        "present": True,
        "status_code": item.status_code,
        "health_score": item.health_score,
    }
    optional = {
        "size_bytes": item.size_bytes,
        "media_errors": item.media_errors,
        "other_errors": item.other_errors,
        "predictive_failures": item.predictive_failures,
        "temperature_c": item.temperature_c,
    }
    fields.update({k: v for k, v in optional.items() if v is not None})
    return Metric(
        measurement=RAID_DRIVE_MEASUREMENT,
        tags={
            "provider": item.provider,
            "controller": item.controller,
            "drive_id": item.drive_id,
            "enclosure": item.enclosure or "unknown",
            "slot": item.slot or "unknown",
            "model": item.model or "unknown",
            "serial": item.serial or "unknown",
            "state": item.state or "unknown",
        },
        fields=fields,
    )


def proxmox_host_info_to_metric(status: ProxmoxHostStatus) -> Metric:
    """Convert stable Proxmox host identity to a metric."""
    return Metric(
        measurement=PROXMOX_HOST_INFO_MEASUREMENT,
        tags={"host": status.host, "node": status.node},
        fields={
            "present": True,
            "pve_version": status.pve_version,
            "kernel_version": status.kernel_version,
            "cpu_model": status.cpu_model,
            "cpu_count": status.cpu_count,
        },
    )


def proxmox_host_status_to_metric(status: ProxmoxHostStatus) -> Metric:
    """Convert one Proxmox host resource snapshot to a metric."""
    return Metric(
        measurement=PROXMOX_HOST_STATUS_MEASUREMENT,
        tags={"host": status.host, "node": status.node},
        fields={
            "uptime_seconds": status.uptime_seconds,
            "cpu_usage_percent": status.cpu_usage_percent,
            "cpu_count": status.cpu_count,
            "load1": status.load1,
            "load5": status.load5,
            "load15": status.load15,
            "memory_total_bytes": status.memory_total_bytes,
            "memory_available_bytes": status.memory_available_bytes,
            "memory_used_bytes": status.memory_used_bytes,
            "memory_used_percent": status.memory_used_percent,
            "swap_total_bytes": status.swap_total_bytes,
            "swap_free_bytes": status.swap_free_bytes,
            "swap_used_bytes": status.swap_used_bytes,
            "swap_used_percent": status.swap_used_percent,
        },
    )


def proxmox_storage_to_metric(status: ProxmoxStorageStatus) -> Metric:
    """Convert Proxmox storage status to a metric."""
    return Metric(
        measurement=PROXMOX_STORAGE_MEASUREMENT,
        tags={"node": status.node, "storage": status.storage, "type": status.storage_type},
        fields={
            "active": status.active, "enabled": status.enabled, "shared": status.shared,
            "total_bytes": status.total_bytes, "used_bytes": status.used_bytes,
            "available_bytes": status.available_bytes, "used_percent": status.used_percent,
            "content": status.content, "health_code": status.health_code,
            "health_status": status.health_status,
        },
    )

def cooling_status_to_metric(status: CoolingStatus) -> Metric:
    mode_code = {
        "quiet": 1,
        "low": 2,
        "boost": 3,
    }.get((status.mode or "").strip().lower(), 0)

    source_code = {
        "manual": 1,
        "hdd_temperature": 2,
        "cpu_temperature": 3,
        "system_temperature": 4,
    }.get((status.source or "").strip().lower(), 0)

    fields: dict[str, bool | int | float | str] = {
        "hdd_input_available": status.hdd_input_available,
        "auto_applied": status.auto_applied,
        "bios_fan_profile": status.bios_fan_profile or "unknown",
        "mode_name": status.mode or "unknown",
        "source_name": status.source or "unknown",
        "mode_code": mode_code,
        "source_code": source_code,
    }
    optional = {
        "pwm2_raw": status.pwm2_raw,
        "pwm2_percent": status.pwm2_percent,
        "cpu_max_c": status.cpu_max_c,
        "system_temp_c": status.system_temp_c,
        "hdd_max_c": status.hdd_max_c,
        "hdd_input_c": status.hdd_input_c,
        "last_change_unix": int(status.last_change) if status.last_change is not None else None,
        "last_update_unix": int(status.last_update) if status.last_update is not None else None,
    }
    fields.update({name: value for name, value in optional.items() if value is not None})
    return Metric(
        measurement=COOLING_STATUS_MEASUREMENT,
        tags={
            "board": status.board or "unknown",
            "controller": status.controller or "unknown",
            "mode": status.mode or "unknown",
            "source": status.source or "unknown",
        },
        fields=fields,
    )


def cooling_fan_metrics(status: CoolingStatus) -> list[Metric]:
    metrics: list[Metric] = []
    for fan_id in range(1, 9):
        rpm = status.fans.get(str(fan_id))
        fields: dict[str, bool | int] = {"available": rpm is not None}
        if rpm is not None:
            fields["rpm"] = int(rpm)
        metrics.append(
            Metric(
                measurement=COOLING_FAN_MEASUREMENT,
                tags={"fan": f"FAN{fan_id}"},
                fields=fields,
            )
        )
    return metrics

def configure_logging() -> None:
    """Configure diagnostic logging on stderr."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _write_metrics(metrics: Iterable[Metric]) -> None:
    """Write only Influx Line Protocol records to stdout."""
    for metric in metrics:
        sys.stdout.write(metric.to_line_protocol())
        sys.stdout.write("\n")


def build_provider_registry() -> ProviderRegistry:
    """Build the enabled provider set using current configuration."""
    registry = ProviderRegistry()
    registry.register(
        StorageProvider(
            inventory_collect=StorageCollector().collect,
            discovery_service_factory=RaidDiscoveryService,
            smart_collect=lambda discovery_service, disks: SmartService(
                discovery=discovery_service
            ).collect(disks),
            visible_disks=storage_visible_disks,
            visible_health=storage_visible_health_results,
            inventory_metrics=build_metrics,
            health_metrics=build_health_metrics,
            status_metrics=build_status_metrics,
        )
    )
    if config.UPS_ENABLED:
        registry.register(
            UPSProvider(
                collect_status=UPSCollector().collect,
                to_metric=ups_status_to_metric,
                required=config.UPS_REQUIRED,
            )
        )
    if config.PROXMOX_ENABLED:
        proxmox_collector = ProxmoxHostCollector(
            sample_interval=config.PROXMOX_CPU_SAMPLE_SECONDS
        )
        proxmox_storage_collector = ProxmoxStorageCollector()
        registry.register(
            ProxmoxProvider(
                collect_status=lambda: proxmox_collector.collect(config.PVEVERSION_BINARY),
                info_metric=proxmox_host_info_to_metric,
                status_metric=proxmox_host_status_to_metric,
                collect_storage=proxmox_storage_collector.collect,
                storage_metric=proxmox_storage_to_metric,
                pveversion_binary=config.PVEVERSION_BINARY,
                required=config.PROXMOX_REQUIRED,
            )
        )
    if config.RAID_ENABLED:
        registry.register(
            RaidProvider(
                collect_status=RaidCollector().collect,
                controller_metric=raid_controller_to_metric,
                array_metric=raid_array_to_metric,
                drive_metric=raid_drive_to_metric,
                required=config.RAID_REQUIRED,
            )
        )
    if config.COOLING_ENABLED:
        registry.register(
            CoolingProvider(
                collect_status=CoolingCollector().collect,
                status_metric=cooling_status_to_metric,
                fan_metrics=cooling_fan_metrics,
                required=config.COOLING_REQUIRED,
            )
        )
    return registry


def main() -> int:
    """Collect all enabled providers and emit Influx Line Protocol."""
    configure_logging()
    registry = build_provider_registry()
    runs = registry.manager().collect()
    MetricsPipeline(_write_metrics).export(runs)
    failed = False
    for run in runs:
        if not run.discovery.ready:
            LOGGER.info("Provider %s skipped: %s", run.provider.name, run.discovery.detail)
            continue
        result = run.result
        if result is None:
            continue
        for warning in result.warnings:
            LOGGER.warning("%s", warning.message)
        for error in result.errors:
            LOGGER.error("%s", error.message)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
