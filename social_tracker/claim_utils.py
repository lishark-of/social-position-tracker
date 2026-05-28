from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


ALIASES_PATH = Path(__file__).with_name("ticker_aliases.json")
CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
ENGLISH_CHAR_RE = re.compile(r"[A-Za-z]")
CASHTAG_RE = re.compile(r"\$([A-Z][A-Z0-9]{1,6})\b")
CN_CODE_RE = re.compile(r"(?<!\d)([036]\d{5}|688\d{3}|159\d{3}|588\d{3}|517\d{3})(?!\d)")
US_TICKER_RE = re.compile(r"(?<![A-Za-z0-9$])([A-Z]{2,6})(?![A-Za-z0-9])")
SPLIT_RE = re.compile(r"(?<=[。！？!?\.])\s+|\n+")
ASCII_TOKEN_RE = re.compile(r"^[A-Za-z0-9 .&+\-]+$")

ACTION_PRIORITY = {
    "空仓": 0,
    "卖出": 0,
    "观察": 1,
    "持有": 2,
    "买入": 3,
}

LEGACY_ACTION_MAP = {
    "buy": "买入",
    "hold": "持有",
    "sell": "卖出",
    "flat": "空仓",
    "watch": "观察",
    "买入": "买入",
    "持有": "持有",
    "卖出": "卖出",
    "空仓": "空仓",
    "观察": "观察",
}

ZH_BUY_TERMS = [
    "买入",
    "买了",
    "建仓",
    "开仓",
    "加仓",
    "低吸",
    "上车",
    "配置",
    "拿了",
    "打了一笔",
    "进了",
    "吸了一点",
]
ZH_HOLD_TERMS = [
    "持有",
    "继续拿",
    "继续持有",
    "格局",
    "锁仓",
    "不动",
    "拿着",
    "先拿",
    "继续看",
    "留着",
]
ZH_SELL_TERMS = [
    "卖出",
    "卖了",
    "减仓",
    "清仓",
    "止盈",
    "止损",
    "割肉",
    "先走",
    "出了",
    "走人",
    "落袋",
    "砍掉",
]
ZH_FLAT_TERMS = [
    "空仓",
    "不碰",
    "暂不参与",
    "回避",
    "避雷",
    "拉黑",
    "不做",
    "没仓位",
    "没买",
    "等以后",
]
ZH_WATCH_TERMS = [
    "观察",
    "关注",
    "看看",
    "等回踩",
    "等确认",
    "加入自选",
    "盯着",
    "跟踪",
    "等机会",
    "先看看",
]
ZH_RISK_TERMS = [
    "风险大",
    "避雷",
    "回避",
    "不碰",
    "有问题",
    "财务有问题",
]
ZH_DISCLOSURE_TERMS = [
    "我买入",
    "我买了",
    "我建仓",
    "我开仓",
    "我加仓",
    "我低吸",
    "我上车",
    "我配置",
    "我拿了",
    "我打了一笔",
    "我进了",
    "我吸了一点",
    "我持有",
    "我继续拿",
    "我继续持有",
    "我锁仓",
    "我拿着",
    "我留着",
    "我卖出",
    "我卖了",
    "我减仓",
    "我清仓",
    "我止盈",
    "我止损",
    "我割肉",
    "我出了",
    "我空仓",
    "我不碰",
    "我回避",
    "我没仓位",
    "我没买",
    "持仓",
    "仓位",
    "我的组合",
]
EN_BUY_TERMS = [
    "buy",
    "bought",
    "add",
    "added",
    "accumulate",
    "long",
    "enter",
    "entry",
    "started a position",
    "opened a position",
    "loading",
    "nibble",
]
EN_HOLD_TERMS = [
    "hold",
    "holding",
    "keep",
    "stay in",
    "still holding",
    "not selling",
    "diamond hands",
]
EN_SELL_TERMS = [
    "sell",
    "sold",
    "trim",
    "trimmed",
    "exit",
    "exited",
    "take profit",
    "stop loss",
    "cut",
    "closed position",
]
EN_FLAT_TERMS = [
    "avoid",
    "no position",
    "cash",
    "stay away",
    "not touching",
    "pass",
    "skip",
    "out of it",
]
EN_WATCH_TERMS = [
    "watch",
    "watchlist",
    "monitor",
    "waiting for setup",
    "tracking",
    "on my radar",
    "watching closely",
]
EN_RISK_TERMS = [
    "too risky",
    "avoid",
    "stay away",
    "not touching",
    "problematic",
    "red flag",
]
EN_OPINION_TERMS = [
    "bullish",
    "looks good",
    "could run",
    "interesting setup",
]
EN_DISCLOSURE_PATTERNS = [
    r"\bi\s+bought\b",
    r"\bi\s+added\b",
    r"\bi\s+am\s+holding\b",
    r"\bi'?m\s+holding\b",
    r"\bi\s+hold\b",
    r"\bi\s+sold\b",
    r"\bi\s+trimmed\b",
    r"\bi\s+closed\s+my\s+position\b",
    r"\bi\s+have\s+no\s+position\b",
    r"\bmy\s+positions?\b",
    r"\bmy\s+portfolio\b",
    r"\bi\s+am\s+long\b",
    r"\bi'?m\s+long\b",
    r"\bstarted\s+a\s+position\b",
    r"\bopened\s+a\s+position\b",
]
US_TICKER_STOPWORDS = {
    "URL",
    "USD",
    "GMT",
    "HTTP",
    "HTTPS",
    "ETF",
    "AI",
    "WSB",
    "IPO",
    "APP",
    "API",
    "CEO",
    "CFO",
    "PDT",
    "EST",
    "CST",
    "RSS",
}


@lru_cache(maxsize=1)
def load_ticker_aliases() -> dict[str, str]:
    return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def detect_language(text: str) -> str:
    chinese_count = len(CHINESE_CHAR_RE.findall(text or ""))
    english_count = len(ENGLISH_CHAR_RE.findall(text or ""))
    if chinese_count == 0 and english_count == 0:
        return "unknown"
    if chinese_count > 0 and english_count > 0:
        total = chinese_count + english_count
        chinese_ratio = chinese_count / total
        english_ratio = english_count / total
        if chinese_ratio >= 0.35 and english_ratio >= 0.35:
            return "mixed"
    if chinese_count > english_count:
        return "zh"
    if english_count > chinese_count:
        return "en"
    return "mixed"


def normalize_source(source: str) -> str:
    value = (source or "").lower()
    if value.startswith("x_") or value.startswith("x"):
        return "x"
    if value.startswith("reddit"):
        return "reddit"
    if value.startswith("web_page") or value == "web":
        return "web"
    if value.startswith("web_search") or value == "search":
        return "search"
    return value or "unknown"


def infer_canonical_ticker(raw_text: str) -> str:
    cleaned = (raw_text or "").strip().replace("$", "")
    if not cleaned:
        return ""
    aliases = load_ticker_aliases()
    for key in (cleaned, cleaned.upper(), cleaned.title()):
        if key in aliases:
            return aliases[key]
    if re.fullmatch(r"159\d{3}", cleaned):
        return f"{cleaned}.SZ"
    if re.fullmatch(r"(588|517)\d{3}", cleaned):
        return f"{cleaned}.SH"
    if re.fullmatch(r"688\d{3}", cleaned):
        return f"{cleaned}.SH"
    if re.fullmatch(r"6\d{5}", cleaned):
        return f"{cleaned}.SH"
    if re.fullmatch(r"[03]\d{5}", cleaned):
        return f"{cleaned}.SZ"
    if re.fullmatch(r"[A-Z]{2,6}", cleaned.upper()):
        return cleaned.upper()
    return cleaned


def build_claim_hash(canonical_ticker: str, action: str, evidence: str, source_url: str, raw_text_hash: str) -> str:
    unique_basis = f"{canonical_ticker}|{action}|{evidence}|{source_url or raw_text_hash}"
    return sha256_text(unique_basis)


def map_legacy_action(value: str) -> str:
    return LEGACY_ACTION_MAP.get((value or "").strip(), "观察")


def _action_rank(action: str) -> int:
    return ACTION_PRIORITY.get(action, -1)


def _text_contains(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    if ASCII_TOKEN_RE.fullmatch(phrase):
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE) is not None
    return phrase in text


def _first_phrase(text: str, phrases: list[str]) -> str:
    for phrase in phrases:
        if _text_contains(text, phrase):
            return phrase
    return ""


def _has_disclosure(text: str) -> tuple[bool, str]:
    for pattern in EN_DISCLOSURE_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True, pattern
    for phrase in ZH_DISCLOSURE_TERMS:
        if phrase in text:
            return True, phrase
    return False, ""


def _has_personal_reference(text: str) -> bool:
    return bool(re.search(r"\b(i|i'm|i’d|i'll|my|me|we|our)\b", text, flags=re.IGNORECASE)) or "我" in text or "本人" in text


def classify_signal(evidence: str, raw_text: str) -> dict[str, Any]:
    text = f"{evidence}\n{raw_text}".strip()
    disclosure, disclosure_reason = _has_disclosure(text)
    personal_ref = _has_personal_reference(text)

    buy_phrase = _first_phrase(text, ZH_BUY_TERMS + EN_BUY_TERMS)
    hold_phrase = _first_phrase(text, ZH_HOLD_TERMS + EN_HOLD_TERMS)
    sell_phrase = _first_phrase(text, ZH_SELL_TERMS + EN_SELL_TERMS)
    flat_phrase = _first_phrase(text, ZH_FLAT_TERMS + EN_FLAT_TERMS)
    watch_phrase = _first_phrase(text, ZH_WATCH_TERMS + EN_WATCH_TERMS + EN_OPINION_TERMS)
    risk_phrase = _first_phrase(text, ZH_RISK_TERMS + EN_RISK_TERMS)

    action = "观察"
    action_reason = "未发现明确动作词，按观察处理"
    if flat_phrase:
        action = "空仓"
        action_reason = f"命中空仓/回避词：{flat_phrase}"
    elif sell_phrase:
        action = "卖出"
        action_reason = f"命中卖出词：{sell_phrase}"
    elif hold_phrase:
        action = "持有"
        action_reason = f"命中持有词：{hold_phrase}"
    elif buy_phrase:
        action = "买入"
        action_reason = f"命中买入词：{buy_phrase}"
    elif watch_phrase:
        action = "观察"
        action_reason = f"命中观察/观点词：{watch_phrase}"

    is_position_disclosure = False
    claim_type = "unknown"
    position_confidence = 0.0
    confidence = 0.4
    confidence_reason = action_reason

    if disclosure and action in {"买入", "持有", "卖出", "空仓"}:
        is_position_disclosure = True
        claim_type = "position_signal"
        position_confidence = 0.92 if personal_ref else 0.75
        confidence = 0.88 if personal_ref else 0.74
        confidence_reason = f"出现明确仓位披露表达（{disclosure_reason}），且动作词清晰。"
    elif risk_phrase or action == "空仓":
        claim_type = "risk_signal"
        action = "空仓" if action in {"空仓", "卖出"} else "观察"
        position_confidence = 0.0
        confidence = 0.58 if risk_phrase else 0.5
        confidence_reason = f"主要体现风险/回避态度（{risk_phrase or action_reason}），不视为真实持仓披露。"
    elif action in {"买入", "持有", "卖出", "观察"}:
        claim_type = "opinion_signal" if (buy_phrase or hold_phrase or sell_phrase or watch_phrase) else "unknown"
        position_confidence = 0.22 if disclosure else 0.0
        if claim_type == "opinion_signal":
            confidence = 0.6 if action in {"买入", "持有", "卖出"} else 0.48
            confidence_reason = f"有明确观点/动作词（{action_reason}），但缺少足够的仓位披露证据，按观点处理。"
        else:
            confidence = 0.38
            confidence_reason = action_reason

    return {
        "action": action,
        "claim_type": claim_type,
        "position_confidence": round(position_confidence, 2),
        "is_position_disclosure": is_position_disclosure,
        "confidence": round(min(max(confidence, 0.0), 1.0), 2),
        "confidence_reason": confidence_reason,
    }


def _ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return max(left[0], right[0]) < min(left[1], right[1])


def extract_ticker_mentions(text: str) -> list[dict[str, Any]]:
    aliases = load_ticker_aliases()
    mentions: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []

    def add_mention(original: str, start: int, end: int) -> None:
        if not original:
            return
        current = (start, end)
        if any(_ranges_overlap(current, span) for span in occupied):
            return
        occupied.append(current)
        mentions.append(
            {
                "original_ticker_text": original,
                "canonical_ticker": infer_canonical_ticker(original),
                "start": start,
                "end": end,
            }
        )

    for alias in sorted(aliases.keys(), key=len, reverse=True):
        if not alias:
            continue
        if CHINESE_CHAR_RE.search(alias):
            start = 0
            while True:
                idx = text.find(alias, start)
                if idx == -1:
                    break
                add_mention(alias, idx, idx + len(alias))
                start = idx + len(alias)
        elif alias.isdigit():
            for match in re.finditer(rf"(?<!\d){re.escape(alias)}(?!\d)", text):
                add_mention(match.group(0), match.start(), match.end())
        else:
            for match in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE):
                add_mention(match.group(0), match.start(), match.end())

    for match in CASHTAG_RE.finditer(text):
        add_mention(match.group(1), match.start(1), match.end(1))

    for match in CN_CODE_RE.finditer(text):
        add_mention(match.group(1), match.start(1), match.end(1))

    for match in US_TICKER_RE.finditer(text):
        candidate = match.group(1).upper()
        if candidate in US_TICKER_STOPWORDS:
            continue
        add_mention(candidate, match.start(1), match.end(1))

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for mention in mentions:
        key = (mention["original_ticker_text"], mention["canonical_ticker"])
        deduped[key] = mention
    return list(deduped.values())


def select_evidence(text: str, mention_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return ""
    mention_lower = mention_text.lower()
    for segment in SPLIT_RE.split(cleaned):
        if mention_lower in segment.lower():
            return segment[:260]
    idx = cleaned.lower().find(mention_lower)
    if idx == -1:
        return cleaned[:260]
    start = max(0, idx - 100)
    end = min(len(cleaned), idx + 160)
    return cleaned[start:end]


def normalize_claim_dict(claim: dict[str, Any], fallback_captured_at: str = "") -> dict[str, Any]:
    original_ticker_text = claim.get("original_ticker_text") or claim.get("ticker") or ""
    canonical_ticker = claim.get("canonical_ticker") or infer_canonical_ticker(original_ticker_text or claim.get("ticker", ""))
    action = claim.get("action") or map_legacy_action(claim.get("stance", ""))
    source_url = claim.get("source_url") or claim.get("url") or ""
    raw_text = claim.get("raw_text") or claim.get("text") or claim.get("evidence") or ""
    raw_text_hash = claim.get("raw_text_hash") or sha256_text(raw_text)
    evidence = claim.get("evidence") or raw_text[:220]
    normalized = {
        "ticker": claim.get("ticker") or canonical_ticker,
        "original_ticker_text": original_ticker_text or canonical_ticker,
        "canonical_ticker": canonical_ticker,
        "action": action,
        "evidence": evidence,
        "confidence": float(claim.get("confidence", 0.0) or 0.0),
        "confidence_reason": claim.get("confidence_reason", ""),
        "claim_type": claim.get("claim_type", "unknown"),
        "position_confidence": float(claim.get("position_confidence", 0.0) or 0.0),
        "is_position_disclosure": bool(claim.get("is_position_disclosure", False)),
        "source": normalize_source(claim.get("source", "")),
        "source_url": source_url,
        "author": claim.get("author", ""),
        "published_at": claim.get("published_at", ""),
        "captured_at": claim.get("captured_at") or claim.get("fetched_at") or fallback_captured_at or "",
        "raw_text": raw_text,
        "raw_text_hash": raw_text_hash,
        "language": claim.get("language", "unknown"),
        "post_id": claim.get("post_id", ""),
        "extractor": claim.get("extractor", "unknown"),
    }
    normalized["claim_hash"] = claim.get("claim_hash") or build_claim_hash(
        normalized["canonical_ticker"],
        normalized["action"],
        normalized["evidence"],
        normalized["source_url"],
        normalized["raw_text_hash"],
    )
    return normalized


def flatten_claims_from_snapshots(snapshots: list[dict[str, Any]], dedupe: bool = False) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    by_hash: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        captured_at = snapshot.get("ran_at", "")
        for claim in snapshot.get("claims", []):
            normalized = normalize_claim_dict(claim, fallback_captured_at=captured_at)
            if dedupe:
                by_hash[normalized["claim_hash"]] = normalized
            else:
                claims.append(normalized)
    if dedupe:
        return list(by_hash.values())
    return claims


def compare_latest_claims(existing_claims: list[dict[str, Any]], latest_claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for latest in latest_claims:
        comparable = [
            item
            for item in existing_claims
            if item.get("canonical_ticker") == latest.get("canonical_ticker")
            and (
                (latest.get("author") and item.get("author") == latest.get("author"))
                or item.get("source") == latest.get("source")
            )
        ]
        comparable.sort(key=lambda item: (item.get("captured_at", ""), item.get("published_at", "")), reverse=True)
        previous = comparable[0] if comparable else None
        change_type = "new"
        previous_action = ""
        previous_evidence = ""
        previous_captured_at = ""
        if previous:
            previous_action = previous.get("action", "")
            previous_evidence = previous.get("evidence", "")
            previous_captured_at = previous.get("captured_at", "")
            latest_rank = _action_rank(latest.get("action", ""))
            previous_rank = _action_rank(previous.get("action", ""))
            if latest_rank > previous_rank:
                change_type = "upgraded"
            elif latest_rank < previous_rank:
                change_type = "downgraded"
            elif latest_rank == previous_rank and latest_rank >= 0:
                change_type = "unchanged"
            else:
                change_type = "unknown"
        comparisons.append(
            {
                "canonical_ticker": latest.get("canonical_ticker", ""),
                "original_ticker_text": latest.get("original_ticker_text", ""),
                "source": latest.get("source", ""),
                "author": latest.get("author", ""),
                "previous_action": previous_action,
                "latest_action": latest.get("action", ""),
                "change_type": change_type,
                "previous_evidence": previous_evidence,
                "latest_evidence": latest.get("evidence", ""),
                "previous_captured_at": previous_captured_at,
                "latest_captured_at": latest.get("captured_at", ""),
            }
        )
    return comparisons


def build_author_position_summary(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in claims:
        normalized = normalize_claim_dict(claim, fallback_captured_at=claim.get("captured_at", ""))
        if normalized.get("claim_type") != "position_signal":
            continue
        if float(normalized.get("position_confidence", 0.0) or 0.0) < 0.5:
            continue
        key = (normalized.get("author", ""), normalized.get("canonical_ticker", ""))
        existing = latest_by_key.get(key)
        if existing is None or (normalized.get("captured_at", ""), normalized.get("published_at", "")) >= (
            existing.get("captured_at", ""),
            existing.get("published_at", ""),
        ):
            latest_by_key[key] = normalized
    rows = []
    for claim in latest_by_key.values():
        rows.append(
            {
                "author": claim.get("author", ""),
                "canonical_ticker": claim.get("canonical_ticker", ""),
                "original_ticker_text": claim.get("original_ticker_text", ""),
                "latest_action": claim.get("action", ""),
                "is_position_disclosure": claim.get("is_position_disclosure", False),
                "position_confidence": claim.get("position_confidence", 0.0),
                "latest_evidence": claim.get("evidence", ""),
                "source": claim.get("source", ""),
                "source_url": claim.get("source_url", ""),
                "latest_captured_at": claim.get("captured_at", ""),
                "latest_published_at": claim.get("published_at", ""),
            }
        )
    rows.sort(key=lambda item: item.get("latest_captured_at", ""), reverse=True)
    return rows
