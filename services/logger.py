"""Central logging helpers for Home Server Monitor services."""

from __future__ import annotations

import logging


_LOGGER_NAME = "home_server_monitor"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a project logger without configuring global logging handlers.

    Applications remain responsible for selecting handlers and log levels.
    A ``NullHandler`` prevents library-style use from emitting warnings when no
    logging configuration has been installed yet.
    """
    root_logger = logging.getLogger(_LOGGER_NAME)
    if not root_logger.handlers:
        root_logger.addHandler(logging.NullHandler())

    if not name:
        return root_logger

    return root_logger.getChild(name)
