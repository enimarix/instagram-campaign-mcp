"""Logging goes to stderr: stdout is the MCP stdio channel and must stay clean."""

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure stdlib logging and structlog. Safe to call again to change level."""
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    # force=True: basicConfig is otherwise a no-op after the first call.
    logging.basicConfig(stream=sys.stderr, level=numeric, force=True)
    # httpx logs every request URL at INFO; token calls carry secrets in the query string.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(max(numeric, logging.WARNING))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        # PrintLogger has no level of its own: filter in the bound logger.
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        # Not cached: modules grab loggers at import time, before main() can
        # apply LOG_LEVEL, and a cached logger would keep the old level.
        cache_logger_on_first_use=False,
    )
