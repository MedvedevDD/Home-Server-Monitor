"""HP Smart Array RAID collector using a narrow ssacli helper."""

from __future__ import annotations

import re

import config
from models.raid import RaidArrayStatus, RaidControllerStatus, RaidDriveStatus
from services.command_runner import CommandNotFoundError, CommandRunner, CommandRunnerError
from services.raid_status import normalize_status


class HpSmartArrayCollectionError(RuntimeError):
    pass


class HpSmartArrayRaidCollector:
    """Collect controller state from HP Smart Array controllers."""

    provider = "hp-smartarray"

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner(config.SSACLI_TIMEOUT_SECONDS)

    def _run(self) -> str:
        command = [config.SSACLI_HELPER]
        if config.SSACLI_USE_SUDO:
            command = ["sudo", "-n", *command]
        try:
            return self.runner.run(command).stdout
        except (CommandNotFoundError, CommandRunnerError) as exc:
            raise HpSmartArrayCollectionError(str(exc)) from exc

    @staticmethod
    def _value(line: str, key: str) -> str | None:
        stripped = line.strip()
        prefix = key + ":"
        if not stripped.startswith(prefix):
            return None
        return stripped[len(prefix):].strip()

    @classmethod
    def parse_controllers(cls, output: str) -> list[RaidControllerStatus]:
        controllers: list[RaidControllerStatus] = []
        current: dict[str, str] | None = None

        def flush() -> None:
            nonlocal current
            if current is None:
                return
            status, code, score = normalize_status(current.get("status", ""))
            slot = current.get("slot", "").strip()
            controllers.append(
                RaidControllerStatus(
                    provider=cls.provider,
                    controller=f"slot{slot}" if slot else "unknown",
                    model=current.get("model", "") or "HP Smart Array",
                    serial=current.get("serial", ""),
                    firmware=current.get("firmware", ""),
                    status=status,
                    status_code=code,
                    health_score=score,
                    cache_status=current.get("cache_status", ""),
                    battery_status=current.get("battery_status", ""),
                    virtual_drive_count=0,
                    physical_drive_count=0,
                    jbod_mode=False,
                )
            )
            current = None

        header_re = re.compile(r"^Smart Array\s+(.+?)\s+in Slot\s+(.+?)\s*$")

        for raw_line in output.splitlines():
            line = raw_line.rstrip()
            match = header_re.match(line.strip())
            if match:
                flush()
                current = {
                    "model": f"Smart Array {match.group(1).strip()}",
                    "slot": match.group(2).strip(),
                }
                continue
            if current is None:
                continue

            for key, field in (
                ("Slot", "slot"),
                ("Serial Number", "serial"),
                ("Controller Status", "status"),
                ("Firmware Version", "firmware"),
                ("Cache Status", "cache_status"),
                ("Battery/Capacitor Status", "battery_status"),
            ):
                value = cls._value(line, key)
                if value is not None:
                    current[field] = value
                    break

        flush()
        return controllers

    def collect(
        self,
    ) -> tuple[list[RaidControllerStatus], list[RaidArrayStatus], list[RaidDriveStatus]]:
        controllers = self.parse_controllers(self._run())
        if not controllers:
            raise HpSmartArrayCollectionError(
                "ssacli helper returned no HP Smart Array controllers"
            )
        return controllers, [], []
