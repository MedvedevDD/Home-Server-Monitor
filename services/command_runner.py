"""Safe execution wrapper for external commands."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CommandResult:
    """Captured result of a completed external command."""

    stdout: str
    stderr: str
    return_code: int


class CommandRunnerError(RuntimeError):
    """Base error raised when a command cannot complete normally."""


class CommandNotFoundError(CommandRunnerError):
    """Raised when the requested executable does not exist."""


class CommandTimeoutError(CommandRunnerError):
    """Raised when an external command exceeds its timeout."""

    def __init__(self, message: str, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class CommandPermissionError(CommandRunnerError):
    """Raised when the operating system refuses to execute a command."""


class CommandRunner:
    """Execute commands without a shell and capture all output."""

    def __init__(self, timeout_seconds: int = 30) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.timeout_seconds = timeout_seconds

    def run(self, command: Sequence[str]) -> CommandResult:
        """Run a command and return stdout, stderr, and its unmodified exit code."""
        if not command or not all(isinstance(item, str) and item for item in command):
            raise ValueError("command must contain non-empty string arguments")

        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise CommandNotFoundError(f"Executable was not found: {command[0]}") from exc
        except PermissionError as exc:
            raise CommandPermissionError(f"Permission denied while executing: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            stdout = self._text(exc.stdout)
            stderr = self._text(exc.stderr)
            raise CommandTimeoutError(
                f"Command timed out after {self.timeout_seconds} seconds: {command[0]}",
                stdout=stdout,
                stderr=stderr,
            ) from exc
        except OSError as exc:
            raise CommandRunnerError(f"Unable to execute {command[0]}: {exc}") from exc

        return CommandResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            return_code=completed.returncode,
        )

    @staticmethod
    def _text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return value
