"""RAID status normalization helpers."""

from __future__ import annotations


def normalize_status(raw: str, *, warning_words: set[str] | None = None,
                     critical_words: set[str] | None = None) -> tuple[str, int, int]:
    text = (raw or "").strip().lower()
    critical = critical_words or {
        "failed", "failure", "degraded", "offline", "missing", "critical",
        "rebuild failed", "not optimal", "dgrd", "offln", "pdgd", "ubad",
    }
    warning = warning_words or {
        "warning", "rebuild", "rebuilding", "verify", "verifying", "checking",
        "initializing", "init", "patrol read", "partially optimal",
    }
    if any(word in text for word in critical):
        return "Critical", 3, 30
    if any(word in text for word in warning):
        return "Warning", 2, 70
    if text in {"ok", "success", "optimal", "optl", "optnl", "online", "onln", "good", "ready", "ugood", "jbod", "ghs", "dhs"}:
        return "Healthy", 1, 100
    if text:
        return "Unknown", 0, 50
    return "Unknown", 0, 50
