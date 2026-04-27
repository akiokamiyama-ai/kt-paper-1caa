"""Translation backends.

Two free endpoints with automatic fallback:

* Google Translate's unofficial ``gtx`` client (primary). Higher quality
  output, no API key required, but the endpoint is unofficial — Google can
  change it without notice.
* MyMemory (fallback). Slower and lower quality, free tier 50,000 chars/day
  when an email is supplied.

If both fail, ``translate()`` returns ``None`` and the caller is expected to
use the original text.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "kt-tribune/0.6 (+local)"
TIMEOUT = 12
TRANSLATE_DELAY = 0.3


def translate_google(text: str, src: str = "en", tgt: str = "ja") -> str | None:
    params = urllib.parse.urlencode(
        {"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text}
    )
    url = f"https://translate.googleapis.com/translate_a/single?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        segments = data[0] if data and data[0] else []
        joined = "".join(seg[0] for seg in segments if seg and seg[0])
        return joined.strip() or None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"  WARN: google translate failed for {text[:40]!r}: {e}", file=sys.stderr)
    return None


def translate_mymemory(text: str, src: str = "en", tgt: str = "ja") -> str | None:
    params = urllib.parse.urlencode(
        {"q": text, "langpair": f"{src}|{tgt}", "de": "tribune@local.test"}
    )
    url = f"https://api.mymemory.translated.net/get?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("responseStatus") == 200:
            t = data.get("responseData", {}).get("translatedText", "").strip()
            if t:
                return t
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"  WARN: mymemory failed for {text[:40]!r}: {e}", file=sys.stderr)
    return None


def translate(text: str, src: str = "en", tgt: str = "ja") -> str | None:
    """Translate via Google (primary) with MyMemory fallback. Empty input passes through."""
    if not text.strip():
        return ""
    t = translate_google(text, src, tgt)
    if t:
        return t
    print("  fallback to MyMemory", file=sys.stderr)
    return translate_mymemory(text, src, tgt)


def translate_meta(articles: list[dict], delay: float = TRANSLATE_DELAY) -> None:
    """Populate ``title_ja`` and ``desc_ja`` keys in-place."""
    for i, a in enumerate(articles):
        print(f"  [{i+1}] translating title+desc: {a['title'][:60]}", file=sys.stderr)
        a["title_ja"] = translate(a["title"]) or a["title"]
        time.sleep(delay)
        a["desc_ja"] = translate(a["desc"]) or a["desc"]
        time.sleep(delay)
