"""Security sanitizer and secure-coding defensive utilities.

Provides defense-in-depth against Cross-Site Scripting (XSS), script injection,
dangerous URI schemes (javascript:, vbscript:, data:text/html), attribute breakout,
and malicious control characters in user-submitted content.
"""

import re
import unicodedata
from urllib.parse import urlparse

# Strict email regex
EMAIL_SAFE_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,63}$"
)

# Allowed safe protocols for links
SAFE_URL_SCHEMES = ("http", "https")


def sanitize_text(text: str | None, max_length: int | None = None) -> str:
    """Sanitize arbitrary user-supplied text for safe persistence and rendering.
    
    1. Null byte removal and control character filtering.
    2. Unicode normalization (NFKC).
    3. Multi-pass tag stripping for <script>, <style>, <iframe>, <object>, <svg>, etc.
    4. General HTML tag removal for plain-text user inputs.
    5. Removal of inline event handlers (onerror=, onload=, etc.).
    6. Neutralization of dangerous pseudo-protocols (javascript:, vbscript:).
    7. Neutralization of unclosed opening tag attempts.
    8. Optional length clamping.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    # 1. Strip null bytes and non-printable control characters (retain \t, \n, \r)
    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # 2. Normalize Unicode to eliminate obfuscated homoglyphs or multi-byte evasion
    text = unicodedata.normalize("NFKC", text)

    # 3. Disarm dangerous pseudo-protocols
    text = re.sub(r"(?:javascript|vbscript)\s*:|data\s*:[^,\s]*text\/html[^,\s]*", "blocked-uri:", text, flags=re.IGNORECASE)

    # 4. Multi-pass tag stripping
    for _ in range(5):
        prev = text
        # Remove dangerous executable elements with their content
        text = re.sub(
            r"<\s*(?:script|style|iframe|object|embed|applet|svg|math)\b[^>]*>.*?</\s*(?:script|style|iframe|object|embed|applet|svg|math)\s*>",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Remove any other HTML tag
        text = re.sub(r"<\s*/?\s*[a-zA-Z!][^>]*>", "", text)
        if text == prev:
            break

    # 5. Disarm inline event handlers
    text = re.sub(r"\bon[a-zA-Z]+\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s>]+)", "", text, flags=re.IGNORECASE)

    # 6. Disarm unclosed opening tags at the end of text (e.g. <img src=x onerror=...)
    text = re.sub(r"<\s*[a-zA-Z!][^>]*$", "", text)

    clean = text.strip()
    if max_length and max_length > 0:
        clean = clean[:max_length]
    return clean


def sanitize_email(email: str | None) -> str:
    """Validate and sanitize an email address, returning empty string if invalid."""
    if not email:
        return ""
    clean = str(email).replace("\x00", "").strip()[:150]
    # Check for CRLF or quote injection attempts
    if any(c in clean for c in "\r\n\t\"'<>;()"):
        return ""
    if not EMAIL_SAFE_REGEX.match(clean):
        return ""
    return clean


def sanitize_url(url: str | None) -> str | None:
    """Validate that a URL uses http/https and contains no script injection."""
    if not url:
        return None
    raw = str(url).replace("\x00", "").strip()
    if any(c in raw for c in " \r\n\t\"'<>"):
        return None
    try:
        parsed = urlparse(raw)
        if parsed.scheme.lower() not in SAFE_URL_SCHEMES:
            return None
        if not parsed.netloc:
            return None
        return raw
    except Exception:
        return None


def is_safe_text(text: str | None) -> bool:
    """Return True if text contains no malicious script/executable patterns."""
    if not text:
        return True
    s = str(text)
    if "\x00" in s:
        return False
    # Check for script, iframe, or event handlers
    if re.search(r"<\s*/?\s*(?:script|iframe|object|embed|svg|style)\b", s, re.IGNORECASE):
        return False
    if re.search(r"\bon[a-zA-Z]+\s*=", s, re.IGNORECASE):
        return False
    if re.search(r"(?:javascript|vbscript)\s*:|data\s*:[^,\s]*text\/html", s, re.IGNORECASE):
        return False
    return True
