"""Find and normalise links in a message.

Links are also found when they are written to dodge filters: "hbl-verify[.]com",
"hxxps://", "jazzcash dot com" or with look-alike Cyrillic letters ("һbl.com").
"""

import re
from urllib.parse import urlsplit

import tldextract

from app.core.text import fold_confusables

# Use the public-suffix snapshot bundled with tldextract; never download at runtime.
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

_LABEL = r"[^\W_][\w-]{0,62}"
_URL = re.compile(
    rf"(?i)\b(?:https?://[^\s<>\"']+|www\.[^\s<>\"']+|{_LABEL}(?:\.[\w-]{{1,63}})*\.[a-z]{{2,24}}(?:/[^\s<>\"']*)?)"
)
_TRAILING = ".,;:!?)]}>'\"۔،"

# File names and similar strings that look like domains but are not links.
_NOT_TLDS = {"jpg", "jpeg", "png", "gif", "pdf", "doc", "docx", "apk", "txt", "mp3", "mp4", "zip"}

_DOT_TRICKS = re.compile(r"(?i)(?<=[\w-])\s*(?:\[\.\]|\(\.\)|\{\.\}|\[dot\]|\(dot\)|\{dot\}|\s+dot\s+)\s*(?=[\w-])")
_HXXP = re.compile(r"(?i)\bh(?:xx|\*\*|tt)p(s?)\s*(?:\[:\]|:)\s*//")


def deobfuscate(text: str) -> str:
    """Undo common link disguises so the real address can be checked."""
    text = _HXXP.sub(lambda m: f"http{m.group(1)}://", text)
    text = _DOT_TRICKS.sub(".", text)
    return text


def _ascii_host(host: str) -> str:
    if host.isascii():
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def extract_urls(text: str, limit: int = 10) -> list[str]:
    found: list[str] = []
    for m in _URL.finditer(deobfuscate(text)):
        raw = m.group(0).rstrip(_TRAILING)
        if "@" in raw:
            continue
        parts = split_url(raw)
        if not parts["registered_domain"] and not parts["is_ip"]:
            continue
        if parts["suffix"] in _NOT_TLDS:
            continue
        # A run of Urdu letters followed by ".com" is not a link unless it is written as one.
        if not parts["host"].isascii() and not fold_confusables(parts["host"]).isascii():
            continue
        url = normalize_url(raw)
        if url not in found:
            found.append(url)
        if len(found) >= limit:
            break
    return found


def normalize_url(raw: str) -> str:
    raw = raw.strip().rstrip(_TRAILING)
    if not re.match(r"(?i)^https?://", raw):
        raw = "http://" + raw
    return raw


def split_url(url: str) -> dict:
    full = normalize_url(url)
    parts = urlsplit(full)
    unicode_host = (parts.hostname or "").lower()
    host = _ascii_host(unicode_host)
    is_ip = bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host))
    ext = _extract(host)
    registered = ext.top_domain_under_public_suffix if not is_ip else ""
    folded = fold_confusables(unicode_host)
    return {
        "url": full,
        "scheme": parts.scheme.lower(),
        "host": host,
        "subdomain": ext.subdomain,
        "domain": ext.domain,
        "suffix": ext.suffix,
        "registered_domain": registered,
        "path": parts.path,
        "is_ip": is_ip,
        "is_punycode": "xn--" in host,
        # "һbl.com" written with a Cyrillic һ folds to "hbl.com".
        "homograph_of": folded if folded != unicode_host and folded.isascii() else None,
    }
