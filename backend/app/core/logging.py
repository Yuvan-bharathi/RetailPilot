"""Logging setup: one-line, key=value records that are easy to grep and to ship later."""

import logging
import logging.config

_FORMAT = "%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s"


def configure_logging(level: str = "INFO") -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": {"format": _FORMAT}},
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "default"},
            },
            "root": {"level": level.upper(), "handlers": ["console"]},
            "loggers": {
                "uvicorn.access": {"level": "WARNING"},
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
