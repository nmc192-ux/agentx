"""AgentX SDK — structured logging helpers."""
import logging


def get_logger(name: str = "agentx_sdk", level: str = "INFO") -> logging.Logger:
    """Return a named logger with a StreamHandler attached (idempotent).

    Calling this function multiple times with the same *name* always returns
    the same logger instance without stacking duplicate handlers.

    Args:
        name:  Logger namespace (default ``"agentx_sdk"``).
        level: Minimum severity to emit — "DEBUG", "INFO", "WARNING", "ERROR".

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(name)s] %(levelname)-8s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        logger.addHandler(handler)

    numeric = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric)
    return logger
