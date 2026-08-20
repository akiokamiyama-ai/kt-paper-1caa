"""第6面 Leisure: 料理コラムを LLM で自律生成（RAG なし、Sprint 4 layout swap で旧 page5 から移動）。

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
from ..lib.jst import jst_today

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

# フィールド間整合チェックの閾値（C178, 2026-08-20）。
#
# 2026-08-20 の 6 面で、料理名「夏ズッキーニとベーコンの洋風レモンバター
# スパゲッティ」に対し本文が「とうもろこしとズッキーニのバターソテー」で、
# ベーコンもスパゲッティも本文に一度も出てこなかった。生成は 1 回の JSON 応答
# なのでパース時の取り違えではなく、``_validate`` が存在チェックと genre 白名単
# しか見ていなかったため素通りしていた。
#
# 判定対象は ``ingredients_summary`` のみ。料理名も見る案は試したが、日本語の
# 「と」で分割すると **「とうもろこし」が割れる**（「ズッキーニととうもろこし」→
# 「うもろこしの…」）ため誤検知源になる。材料欄はカンマ区切りで曖昧さがない。
#
# archive 115 日を走査した実測（材料が本文に出現するか）:
#
#   未出現 0 件: 88 日 / 1 件: 22 日 / 2 件: 1 日
#
# 2 件がちょうど 8/20 の 1 日だけで、完全に分離できる。1 件の 22 日は
# 「豚こま切れ」対本文「豚肉」のような表記ゆれで、本文は料理名と整合していた。
# よって閾値は 2 件（発火率 0.9%、誤検知ゼロ）。
CONSISTENCY_MISSING_THRESHOLD: int = 2

# 材料名が本文に「出現した」と見なす最長共通部分文字列の比率。
# 「夏トマト」対「トマト」/「絹ごし豆腐」対「豆腐」のような表記ゆれを吸収する。
CONSISTENCY_MATCH_RATIO: float = 0.5

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
# Field consistency (C178)
# ---------------------------------------------------------------------------

_PAREN_RE = re.compile(r"[（(].*?[)）]")
_INGREDIENT_SPLIT_RE = re.compile(r"[、,／/･・]")


def _appears_in_body(term: str, body: str) -> bool:
    """``term`` が ``body`` に実質的に出現するか（表記ゆれを許容）.

    完全一致だと「夏トマト」対本文「トマト」で落ちるので、term の最長連続
    部分文字列が body に含まれ、それが term の ``CONSISTENCY_MATCH_RATIO``
    以上を占めれば出現と見なす。
    """
    t = _PAREN_RE.sub("", term).strip()
    if not t:
        return True
    if len(t) <= 2:
        return t in body
    n = len(t)
    for length in range(n, 1, -1):
        for start in range(0, n - length + 1):
            if t[start : start + length] in body:
                return length / n >= CONSISTENCY_MATCH_RATIO
    return False


def _missing_terms(parsed: dict) -> list[str]:
    """材料欄のうち、本文に出てこない材料を返す（C178）.

    材料欄と本文が別の料理を指していれば、材料の複数が本文に現れない。
    8/20 は「ベーコン」「スパゲッティ」の 2 件が該当した。
    """
    body = parsed.get("column_body") or ""
    if not body:
        return []
    terms = [
        x.strip()
        for x in _INGREDIENT_SPLIT_RE.split(parsed.get("ingredients_summary") or "")
        if x.strip()
    ]
    return [t for t in terms if not _appears_in_body(t, body)]


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
        target_date = jst_today()
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
            tag="page6.cooking",
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

    # C178: フィールド間整合チェック（存在チェックだけでは 8/20 を素通りさせた）
    missing = _missing_terms(parsed)
    if 0 < len(missing) < CONSISTENCY_MISSING_THRESHOLD:
        # 閾値未満でも残す。後から閾値の妥当性を検証できるようにするため。
        print(
            f"[cooking] debug: 本文に出てこない要素 {len(missing)} 件 "
            f"{missing}（閾値 {CONSISTENCY_MISSING_THRESHOLD} 未満、そのまま採用）",
            file=sys.stderr,
        )
    elif len(missing) >= CONSISTENCY_MISSING_THRESHOLD:
        print(
            f"[cooking] WARN: フィールド不整合を検知 — 本文に出てこない要素 "
            f"{len(missing)} 件 {missing}（料理名: {parsed['dish_name']}）。"
            "1 回だけ再生成します",
            file=sys.stderr,
        )
        try:
            retry_resp = llm.call_claude_with_retry(
                system=COOKING_SYSTEM,
                user=user_msg,
                model=model,
                max_tokens=DEFAULT_MAX_TOKENS,
                cache_system=True,
                tag="page6.cooking.retry",
            )
            cost += retry_resp.cost_usd
            retry_parsed, retry_parse_err = _parse_response(retry_resp.text)
            retry_validation_err = _validate(retry_parsed)
            if retry_validation_err is not None:
                print(
                    "[cooking] WARN: 再生成が invalid "
                    f"({retry_parse_err or retry_validation_err}) — 初回の結果を採用します",
                    file=sys.stderr,
                )
            else:
                retry_missing = _missing_terms(retry_parsed)
                if len(retry_missing) < CONSISTENCY_MISSING_THRESHOLD:
                    print(
                        f"[cooking] 再生成で整合しました（未出現 {len(missing)} → "
                        f"{len(retry_missing)} 件、料理名: {retry_parsed['dish_name']}）",
                        file=sys.stderr,
                    )
                    parsed = retry_parsed
                else:
                    # 静的 fallback には落とさない。不整合は表示上の瑕疵であって
                    # 紙面は成立しており、「鮭の塩焼き定食」に落ちる方が損失が大きい。
                    print(
                        f"[cooking] WARN: 再生成も不整合（未出現 {len(retry_missing)} 件 "
                        f"{retry_missing}）— 未出現が少ない方を採用します",
                        file=sys.stderr,
                    )
                    if len(retry_missing) < len(missing):
                        parsed = retry_parsed
        except Exception as e:  # noqa: BLE001
            print(
                f"[cooking] WARN: 再生成の呼び出しに失敗 ({type(e).__name__}: "
                f"{llm.redact_key(str(e))[:120]}) — 初回の結果を採用します",
                file=sys.stderr,
            )

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
