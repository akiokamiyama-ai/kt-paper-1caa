"""第5面 Leisure: 料理コラムを LLM で自律生成（RAG なし）。

Pipeline:

1. logs/cooking_history.json から過去 EXCLUSION_DAYS=30 日の履歴取得
2. 直近3日のジャンル（和・洋・中・エスニック）を抽出
3. プロンプト構築：current_month / current_season / 過去30日履歴 / 直近3ジャンル
4. LLM 呼出（Sonnet 4.6, temperature=0.8、料理は多様性重視で少し高め）
5. JSON parse: dish_name + ingredients_summary + genre + column_title + column_body
6. logs/cooking_history.json に追記
7. 失敗時は static fallback（鮭の塩焼き定食）
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from ..lib import llm
from .prompts import COOKING_SYSTEM, COOKING_USER_TEMPLATE

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
HISTORY_PATH = LOG_DIR / "cooking_history.json"

DEFAULT_MODEL = llm.DEFAULT_MODEL
DEFAULT_MAX_TOKENS = 1500
DEFAULT_TEMPERATURE = 0.8

EXCLUSION_DAYS: int = 30
RECENT_GENRE_LOOKBACK_DAYS: int = 3
ALLOWED_GENRES: tuple[str, ...] = ("和", "洋", "中", "エスニック")

_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE | re.MULTILINE
)


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------

def load_history(*, path: Path | None = None) -> dict:
    p = path or HISTORY_PATH
    if not p.exists():
        return {"history": []}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"history": []}
    if "history" not in data or not isinstance(data["history"], list):
        return {"history": []}
    return data


def save_history(data: dict, *, path: Path | None = None) -> None:
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_history(
    *,
    dish_name: str,
    genre: str,
    target_date: date,
    history: dict | None = None,
    persist: bool = True,
    path: Path | None = None,
) -> dict:
    if history is None:
        history = load_history(path=path)
    history.setdefault("history", []).append({
        "dish_name": dish_name,
        "genre": genre,
        "date": target_date.isoformat(),
    })
    if persist:
        save_history(history, path=path)
    return history


# ---------------------------------------------------------------------------
# Season / month helper
# ---------------------------------------------------------------------------

def get_season(month: int) -> str:
    """月 → 季節（春・夏・秋・冬）."""
    if month in (3, 4, 5):
        return "春"
    if month in (6, 7, 8):
        return "夏"
    if month in (9, 10, 11):
        return "秋"
    return "冬"


# ---------------------------------------------------------------------------
# History queries (for prompt building)
# ---------------------------------------------------------------------------

def recent_dish_names(history: dict, today: date, days: int = EXCLUSION_DAYS) -> list[str]:
    """過去 ``days`` 日以内に提案された dish_name の一覧."""
    cutoff = today.toordinal() - days
    out: list[str] = []
    for entry in history.get("history", []):
        d_str = entry.get("date", "")
        try:
            d = date.fromisoformat(d_str)
        except (ValueError, TypeError):
            continue
        if d.toordinal() >= cutoff:
            name = entry.get("dish_name")
            if name:
                out.append(name)
    return out


def recent_genres(history: dict, today: date, days: int = RECENT_GENRE_LOOKBACK_DAYS) -> list[str]:
    """直近 ``days`` 日以内のジャンル一覧（重複あり、新→旧順）."""
    cutoff = today.toordinal() - days
    out: list[str] = []
    # Newest first
    for entry in reversed(history.get("history", [])):
        d_str = entry.get("date", "")
        try:
            d = date.fromisoformat(d_str)
        except (ValueError, TypeError):
            continue
        if d.toordinal() >= cutoff:
            g = entry.get("genre")
            if g:
                out.append(g)
        else:
            break
    return out


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_user_message(today: date, history: dict) -> str:
    month = today.month
    season = get_season(month)
    history_dishes = recent_dish_names(history, today)
    if history_dishes:
        # Show as a simple Japanese-style bullet list
        history_str = "  - " + "\n  - ".join(history_dishes)
    else:
        history_str = "  （過去30日履歴なし）"
    recent_g = recent_genres(history, today)
    if recent_g:
        recent_str = ", ".join(recent_g)
    else:
        recent_str = "なし"
    return COOKING_USER_TEMPLATE.format(
        current_month=month,
        current_season=season,
        history_dish_names=history_str,
        recent_genres=recent_str,
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(raw_text: str) -> tuple[dict | None, str | None]:
    if not raw_text:
        return None, "empty_response"
    text = _FENCE_RE.sub("", raw_text).strip()
    if not text.startswith("{"):
        idx = text.find("{")
        if idx < 0:
            return None, "no_json_object_found"
        text = text[idx:]
    end = text.rfind("}")
    if end >= 0:
        text = text[: end + 1]
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"json_decode_error: {e.msg}"


REQUIRED_KEYS: tuple[str, ...] = (
    "dish_name", "ingredients_summary", "genre", "column_title", "column_body",
)


def _validate(parsed: dict | None) -> str | None:
    """Returns None if valid, error string otherwise."""
    if not isinstance(parsed, dict):
        return "not_a_dict"
    for k in REQUIRED_KEYS:
        v = parsed.get(k)
        if not isinstance(v, str) or not v.strip():
            return f"missing_or_empty:{k}"
    if parsed["genre"] not in ALLOWED_GENRES:
        return f"invalid_genre:{parsed['genre']}"
    return None


# ---------------------------------------------------------------------------
# Static fallback
# ---------------------------------------------------------------------------

STATIC_FALLBACK_BODY = (
    "塩鮭はそのままでも十分美味しいが、家庭の朝食・夕食の両方に座る息の長い1皿。"
    "脂のりは塩漬けの効きで決まり、強火短時間でこんがり仕上げると、香ばしさと"
    "ふっくら感が両立する。ご飯と味噌汁、漬物または小鉢一品を添えれば「整う」"
    "という言葉がふさわしい完成形になる。今日のような迷う夕方には、奇をてらわず"
    "に塩鮭を選ぶのも一つの知恵だろう。"
)


def static_fallback() -> dict:
    return {
        "dish_name": "鮭の塩焼き定食",
        "ingredients_summary": "塩鮭、ご飯、味噌汁、小鉢",
        "genre": "和",
        "column_title": "定番の安心感",
        "column_body": STATIC_FALLBACK_BODY,
        "is_fallback": True,
        "cost_usd": 0.0,
    }


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def generate_cooking_column(
    *,
    target_date: date | None = None,
    history: dict | None = None,
    persist: bool = True,
    history_path: Path | None = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Generate today's cooking column.

    Returns::

        {
            "dish_name": str,
            "ingredients_summary": str,
            "genre": str,
            "column_title": str,
            "column_body": str,
            "is_fallback": bool,
            "cost_usd": float,
        }
    """
    if target_date is None:
        target_date = date.today()
    if history is None:
        history = load_history(path=history_path)

    user_msg = _build_user_message(target_date, history)

    try:
        response = llm.call_claude_with_retry(
            system=COOKING_SYSTEM,
            user=user_msg,
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            cache_system=True,
        )
        cost = response.cost_usd
        parsed, parse_err = _parse_response(response.text)
        validation_err = _validate(parsed)
        if validation_err is not None:
            print(
                f"[cooking] WARN: invalid response ({parse_err or validation_err}), "
                "static fallback",
                file=sys.stderr,
            )
            result = static_fallback()
            result["cost_usd"] = cost  # cost incurred even on fallback
            return result
    except Exception as e:
        print(
            f"[cooking] WARN: LLM failed ({type(e).__name__}: "
            f"{llm.redact_key(str(e))[:200]}), static fallback",
            file=sys.stderr,
        )
        return static_fallback()

    # Success: persist history + return
    if persist:
        append_history(
            dish_name=parsed["dish_name"],
            genre=parsed["genre"],
            target_date=target_date,
            history=history,
            persist=persist,
            path=history_path,
        )

    return {
        "dish_name": parsed["dish_name"].strip(),
        "ingredients_summary": parsed["ingredients_summary"].strip(),
        "genre": parsed["genre"].strip(),
        "column_title": parsed["column_title"].strip(),
        "column_body": parsed["column_body"].strip(),
        "is_fallback": False,
        "cost_usd": cost,
    }
