import logging
import uuid

logger = logging.getLogger(__name__)


def safe_error(exc: Exception, context: str) -> str:
    """
    Logs the full exception server-side (with a correlation id so it can
    be found in logs) and returns a generic, secret-free message safe to
    send to an API client.
    """
    error_id = uuid.uuid4().hex[:8]
    logger.exception("[%s] %s", error_id, context)
    return f"{context}. Reference: {error_id}. Check server logs for details."
