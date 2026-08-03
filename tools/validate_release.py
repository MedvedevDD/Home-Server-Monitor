#!/usr/bin/env python3
"""Validate release files without requiring a running HSM installation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    required = [
        "VERSION",
        "collector.py",
        "hsm.py",
        "install.sh",
        "update.sh",
        "docs/CONFIGURATION.md",
        "docs/ARCHITECTURE.md",
        "docs/ROADMAP.md",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        print("Missing required files: " + ", ".join(missing), file=sys.stderr)
        return 1

    dashboards = root / "dashboard"
    expected = {"Home.json", "Storage.json", "RAID.json", "UPS.json", "Proxmox.json"}
    present = {path.name for path in dashboards.glob("*.json")}
    if present != expected:
        print(f"Unexpected dashboard set: {sorted(present)}", file=sys.stderr)
        return 1
    for path in dashboards.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))

    forbidden = [path for path in root.rglob("*") if path.name == "__pycache__" or path.suffix == ".pyc"]
    if forbidden:
        print("Generated Python cache files are present", file=sys.stderr)
        return 1

    print(f"Release { (root / 'VERSION').read_text().strip() } validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
