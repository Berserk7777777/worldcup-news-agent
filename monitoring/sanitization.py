import re


REDACTIONS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE), "[API_KEY_REDACTED]"),
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer [TOKEN_REDACTED]"),
    (
        re.compile(r"Authorization:\s*\S+", re.IGNORECASE),
        "Authorization: [REDACTED]",
    ),
    (
        re.compile(r"api[_-]?key\s*[:=]\s*\S+", re.IGNORECASE),
        "api_key=[REDACTED]",
    ),
]


def sanitize_text(text: str, secrets: list[str] | None = None) -> str:
    cleaned = str(text or "")
    for pattern, replacement in REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    for secret in secrets or []:
        if secret:
            cleaned = cleaned.replace(secret, "[SECRET_REDACTED]")
    return cleaned


def sanitize_error(error: Exception, secrets: list[str] | None = None) -> str:
    return safe_summary(sanitize_text(str(error), secrets), 500)


def safe_summary(text: str, max_length: int = 300) -> str:
    value = str(text or "").strip()
    if max_length <= 0:
        return ""
    if len(value) <= max_length:
        return value
    if max_length == 1:
        return "…"
    return value[: max_length - 1] + "…"
