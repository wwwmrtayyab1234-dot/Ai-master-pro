from services.firebase_auth_service import MAINTENANCE_MESSAGE, OFFLINE_MESSAGE
from services.crash_service import report_exception


def friendly_error(error: Exception) -> str:
    """Convert provider/transport errors into stable user-facing English."""
    report_exception(error, "Handled provider or UI operation failure")
    if isinstance(error, (ValueError, FileNotFoundError)):
        return str(error)
    message = str(error).strip()
    lowered = message.lower()
    if OFFLINE_MESSAGE.lower() in lowered or any(
        marker in lowered
        for marker in (
            "urlopen error",
            "name or service not known",
            "network is unreachable",
            "connection refused",
            "connection timed out",
            "temporary failure in name resolution",
        )
    ):
        return OFFLINE_MESSAGE
    if any(
        marker in lowered
        for marker in (
            "429",
            "rate limit",
            "quota",
            "overloaded",
            "503",
            "502",
            "server error",
            "service unavailable",
            "timed out",
            "timeout",
        )
    ):
        return MAINTENANCE_MESSAGE
    safe_messages = (
        "missing from the .env file",
        "not configured",
        "not supported",
        "must be smaller",
        "could not be found",
        "verify your email",
        "password",
        "email",
        "account",
    )
    if any(marker in lowered for marker in safe_messages) and len(message) < 240:
        return message
    return MAINTENANCE_MESSAGE
