"""Input/output security controls independent of model behavior."""

import re
from dataclasses import dataclass

INJECTION_PATTERNS = (
    r"\bignore\s+(all\s+)?(previous|prior|above|system)\s+instructions?\b",
    r"\b(disregard|override|bypass)\s+(the\s+)?(rules?|policy|guardrails?|instructions?)\b",
    r"\b(reveal|show|print|repeat|echo|dump)\s+(the\s+)?(?:(hidden|initial)\s+)?(system|developer)\s+(prompt|message|instructions?)\b",
    r"\byou are now\b",
    r"\bact as\s+(an?\s+)?unrestricted\b",
    r"<\s*/?\s*(system|developer|assistant|tool)[^>]*>",
    r"\bBEGIN\s+(SYSTEM|DEVELOPER)\s+(PROMPT|MESSAGE)\b",
)
SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|lsv2_[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----"),
)


@dataclass(frozen=True)
class SecurityCheck:
    allowed: bool
    reason: str | None = None


def inspect_prompt(text: str) -> SecurityCheck:
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return SecurityCheck(False, "Potential prompt-injection or instruction-extraction attempt detected.")
    if "\x00" in text or sum(ord(char) < 32 and char not in "\n\r\t" for char in text):
        return SecurityCheck(False, "Unsupported control characters detected.")
    return SecurityCheck(True)


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def safe_for_learning(query: str, response: str) -> bool:
    """Prevent malicious instructions or secret-bearing content entering memory."""
    return inspect_prompt(query).allowed and inspect_prompt(response).allowed and redact_secrets(response) == response
