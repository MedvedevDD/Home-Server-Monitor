"""Normalized RAID collectors for StorCLI and 3ware tw_cli."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

import config
from models.raid import RaidArrayStatus, RaidControllerStatus, RaidDriveStatus
from services.command_runner import CommandNotFoundError, CommandRunner, CommandRunnerError
from services.raid_status import normalize_status
from services.hp_smartarray import (
    HpSmartArrayCollectionError,
    HpSmartArrayRaidCollector,
)

LOGGER = logging.getLogger("home_server_monitor.raid")


class RaidCollectionError(RuntimeError):
    pass


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value.replace(",", ""))
        return int(match.group(0)) if match else None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        return float(match.group(0)) if match else None
    return None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first(mapping: Mapping[str, Any], *names: str) -> Any:
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _size_bytes(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if not isinstance(value, str):
        return None
    match = re.search(r"([0-9.]+)\s*(TB|GB|MB|KB|B)", value, re.I)
    if not match:
        return None
    factor = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}[match.group(2).upper()]
    return int(float(match.group(1)) * factor)


class StorCliRaidCollector:
    provider = "megaraid"

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner(config.STORCLI_TIMEOUT_SECONDS)

    def _run(self, args: list[str]) -> Mapping[str, Any]:
        command = [config.STORCLI_BINARY, *args, "J"]
        if config.STORCLI_USE_SUDO:
            command = ["sudo", *command]
        try:
            result = self.runner.run(command)
        except (CommandNotFoundError, CommandRunnerError) as exc:
            raise RaidCollectionError(str(exc)) from exc
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RaidCollectionError("StorCLI returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise RaidCollectionError("StorCLI JSON root is not an object")
        return payload

    @staticmethod
    def _responses(payload: Mapping[str, Any]):
        controllers = payload.get("Controllers")
        if not isinstance(controllers, Sequence) or isinstance(controllers, (str, bytes)):
            return
        for index, item in enumerate(controllers):
            if not isinstance(item, Mapping):
                continue
            response = item.get("Response Data")
            if isinstance(response, Mapping):
                yield index, item, response

    @staticmethod
    def _detail_identity(key: str, value: Mapping[str, Any]) -> tuple[str, str, str] | None:
        text = key + " " + " ".join(str(v) for v in value.values() if isinstance(v, str))
        path = re.search(r"/c(\d+)(?:/e(\d+))?/s(\d+)", text, re.I)
        if path:
            return path.group(1), path.group(2) or "", path.group(3)
        eid_slt = _text(_first(value, "EID:Slt", "EID:SLOT"))
        if ":" in eid_slt:
            enclosure, slot = eid_slt.split(":", 1)
            controller = str(_as_int(_first(value, "Controller")) or 0)
            return controller, enclosure, slot
        return None

    @classmethod
    def _drive_detail_index(cls, payload: Mapping[str, Any]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
        index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
        for controller_index, _item, response in cls._responses(payload):
            for key, value in response.items():
                if not isinstance(value, Mapping):
                    continue
                identity = cls._detail_identity(str(key), value)
                if identity is None:
                    continue
                controller, enclosure, slot = identity
                if not controller:
                    controller = str(controller_index)
                current = dict(index.get((controller, enclosure, slot), {}))
                for nested_key, nested_value in value.items():
                    if isinstance(nested_value, Mapping):
                        current.update(nested_value)
                    else:
                        current[nested_key] = nested_value
                index[(controller, enclosure, slot)] = current
        return index

    def collect(self) -> tuple[list[RaidControllerStatus], list[RaidArrayStatus], list[RaidDriveStatus]]:
        payload = self._run(["/call", "show", "all"])
        try:
            detail_payload = self._run(["/call", "/eall", "/sall", "show", "all"])
            detail_index = self._drive_detail_index(detail_payload)
        except (RaidCollectionError, IndexError) as exc:
            LOGGER.warning("StorCLI detailed drive data unavailable: %s", exc)
            detail_index = {}
        controllers: list[RaidControllerStatus] = []
        arrays: list[RaidArrayStatus] = []
        drives: list[RaidDriveStatus] = []

        for index, item, response in self._responses(payload):
            command_status = item.get("Command Status") if isinstance(item.get("Command Status"), Mapping) else {}
            command_controller = _as_int(_first(command_status, "Controller"))
            response_controller = _as_int(_first(response, "Controller"))
            controller_id = str(command_controller if command_controller is not None else (response_controller if response_controller is not None else index))
            basics = next((v for k, v in response.items() if "basics" in str(k).lower() and isinstance(v, Mapping)), response)
            raw_status = (_text(_first(basics, "Status", "Controller Status"))
                          or _text(_first(response, "Status"))
                          or _text(_first(command_status, "Status")))
            status, code, score = normalize_status(raw_status)
            array_start = len(arrays)
            drive_start = len(drives)
            controllers.append(RaidControllerStatus(
                provider=self.provider,
                controller=controller_id,
                model=_text(_first(basics, "Model", "Product Name", "Controller Model")),
                serial=_text(_first(basics, "Serial Number", "Serial")),
                firmware=_text(_first(basics, "FW Package Build", "Firmware Version", "FW Version")),
                status=status,
                status_code=code,
                health_score=score,
                temperature_c=_as_float(_first(basics, "ROC temperature(Degree Celsius)", "Controller Temperature", "Temperature")),
                cache_status=_text(_first(basics, "Current Personality", "Cachevault_Info", "Cache Status")),
                battery_status=_text(_first(basics, "BBU Status", "Battery Status", "CV Status")),
                patrol_read_status=_text(_first(basics, "Patrol Read Status", "PR Status")),
            ))

            for key, value in response.items():
                key_l = str(key).lower()
                if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                    continue
                rows = [row for row in value if isinstance(row, Mapping)]
                if ("vd list" in key_l or "virtual drive" in key_l) and rows:
                    for row in rows:
                        dg_vd = _text(_first(row, "DG/VD", "VD", "Virtual Drive"))
                        raw = _text(_first(row, "State", "Status"))
                        st, sc, hs = normalize_status(raw)
                        arrays.append(RaidArrayStatus(
                            provider=self.provider,
                            controller=controller_id,
                            array_id=dg_vd or _text(_first(row, "VD")) or "unknown",
                            name=_text(_first(row, "Name")),
                            raid_level=_text(_first(row, "TYPE", "RAID", "RAID Level")),
                            status=st, status_code=sc, health_score=hs,
                            size_bytes=_size_bytes(_first(row, "Size")),
                        ))
                if ("pd list" in key_l or "drive" in key_l) and rows:
                    for row in rows:
                        did = _text(_first(row, "DID", "Device ID", "Device Id"))
                        eid_slt = _text(_first(row, "EID:Slt", "EID:SLOT"))
                        enclosure, slot = "", ""
                        if ":" in eid_slt:
                            enclosure, slot = eid_slt.split(":", 1)
                        state = _text(_first(row, "State", "Status"))
                        st, sc, hs = normalize_status(state)
                        media = _as_int(_first(row, "Media Error Count", "Med Err"))
                        other = _as_int(_first(row, "Other Error Count", "Other Err"))
                        predictive = _as_int(_first(row, "Predictive Failure Count", "Predictive Failure", "Pred Fail"))
                        if any((media or 0, predictive or 0)):
                            st, sc, hs = "Warning", 2, 70
                        detail = detail_index.get((controller_id, enclosure, slot), {})
                        drives.append(RaidDriveStatus(
                            provider=self.provider, controller=controller_id,
                            drive_id=did or eid_slt or "unknown", enclosure=enclosure, slot=slot,
                            model=(_text(_first(row, "Model", "Inquiry Data"))
                                   or _text(_first(detail, "Model Number", "Model", "Inquiry Data"))),
                            serial=(_text(_first(row, "SN", "Serial Number"))
                                    or _text(_first(detail, "SN", "Serial Number", "Drive Serial Number"))),
                            state=state, status=st, status_code=sc, health_score=hs,
                            size_bytes=_size_bytes(_first(row, "Size")),
                            media_errors=media, other_errors=other,
                            predictive_failures=predictive,
                            temperature_c=(_as_float(_first(row, "Drive Temperature", "Temperature"))
                                           if _as_float(_first(row, "Drive Temperature", "Temperature")) is not None
                                           else _as_float(_first(detail, "Drive Temperature", "Temperature"))),
                        ))

            controller = controllers[-1]
            controller_arrays = len(arrays) - array_start
            controller_drives = len(drives) - drive_start
            controllers[-1] = RaidControllerStatus(
                provider=controller.provider, controller=controller.controller,
                model=controller.model, serial=controller.serial, firmware=controller.firmware,
                status=controller.status, status_code=controller.status_code,
                health_score=controller.health_score, temperature_c=controller.temperature_c,
                cache_status=controller.cache_status, battery_status=controller.battery_status,
                patrol_read_status=controller.patrol_read_status,
                virtual_drive_count=controller_arrays, physical_drive_count=controller_drives,
                jbod_mode=controller_arrays == 0 and controller_drives > 0,
            )
        return controllers, arrays, drives


class ThreeWareRaidCollector:
    provider = "3ware"

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner(config.TWCLI_TIMEOUT_SECONDS)

    def _run(self, args: list[str]) -> str:
        command = [config.TWCLI_BINARY, *args]
        if config.TWCLI_USE_SUDO:
            command = ["sudo", *command]
        try:
            return self.runner.run(command).stdout
        except (CommandNotFoundError, CommandRunnerError) as exc:
            raise RaidCollectionError(str(exc)) from exc

    def collect(self) -> tuple[list[RaidControllerStatus], list[RaidArrayStatus], list[RaidDriveStatus]]:
        listing = self._run(["show"])
        controller_ids = re.findall(r"\bc(\d+)\b", listing)
        controllers: list[RaidControllerStatus] = []
        arrays: list[RaidArrayStatus] = []
        drives: list[RaidDriveStatus] = []
        for cid in sorted(set(controller_ids), key=int):
            detail = self._run([f"/c{cid}", "show"])
            model = firmware = serial = raw_status = ""
            for line in detail.splitlines():
                key, sep, value = line.partition("=")
                if not sep:
                    continue
                k = key.strip().lower()
                value = value.strip()
                if "model" in k: model = value
                elif "firmware" in k: firmware = value
                elif "serial" in k: serial = value
                elif k.endswith("status"): raw_status = value
            st, sc, hs = normalize_status(raw_status or "OK")
            array_start = len(arrays)
            drive_start = len(drives)
            controllers.append(RaidControllerStatus(self.provider, cid, model, serial, firmware, st, sc, hs))

            for line in detail.splitlines():
                columns = line.split()
                if not columns:
                    continue
                if re.fullmatch(r"u\d+", columns[0]):
                    raw = columns[2] if len(columns) > 2 else ""
                    ast, asc, ahs = normalize_status(raw)
                    arrays.append(RaidArrayStatus(
                        self.provider, cid, columns[0],
                        raid_level=columns[1] if len(columns) > 1 else "",
                        status=ast, status_code=asc, health_score=ahs,
                        size_bytes=_size_bytes(" ".join(columns)),
                    ))
                elif re.fullmatch(r"p\d+", columns[0]):
                    raw = columns[1] if len(columns) > 1 else ""
                    dst, dsc, dhs = normalize_status(raw)
                    drives.append(RaidDriveStatus(
                        self.provider, cid, columns[0], slot=columns[0][1:],
                        state=raw, status=dst, status_code=dsc, health_score=dhs,
                        size_bytes=_size_bytes(" ".join(columns)),
                        model=" ".join(columns[6:]) if len(columns) > 6 else "",
                    ))
        return controllers, arrays, drives


class RaidCollector:
    """Run every available RAID provider without breaking other collectors."""

    def collect(self) -> tuple[list[RaidControllerStatus], list[RaidArrayStatus], list[RaidDriveStatus]]:
        all_controllers: list[RaidControllerStatus] = []
        all_arrays: list[RaidArrayStatus] = []
        all_drives: list[RaidDriveStatus] = []
        providers = []
        if config.RAID_STORCLI_ENABLED:
            providers.append(StorCliRaidCollector())
        if config.RAID_SSACLI_ENABLED:
            providers.append(HpSmartArrayRaidCollector())
        if config.RAID_TWCLI_ENABLED:
            providers.append(ThreeWareRaidCollector())
        for provider in providers:
            try:
                controllers, arrays, drives = provider.collect()
            except (RaidCollectionError, HpSmartArrayCollectionError) as exc:
                LOGGER.warning("RAID provider %s skipped: %s", provider.provider, exc)
                continue
            all_controllers.extend(controllers)
            all_arrays.extend(arrays)
            all_drives.extend(drives)
        return all_controllers, all_arrays, all_drives
