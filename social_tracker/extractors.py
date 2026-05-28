from __future__ import annotations

import json
import re
from typing import Any

import requests

from .models import PositionClaim, PostRecord


TICKER_PATTERN = re.compile(r"\$([A-Z][A-Z0-9]{1,6})\b")
POSITIVE_HOLD_PATTERNS = [
    r"\bmy\s+\$?[A-Z0-9]{1,6}\s+positions?\b",
    r"\bmy\s+positions?\b",
    r"\bmy\s+long\b",
    r"\bi(?:'m| am)\s+long\b",
    r"\bholding\b",
    r"\bstill up\b",
    r"\bown\b",
]
POSITIVE_BUY_PATTERNS = [
    r"\bi bought\b",
    r"\badding\b",
    r"\baccumulating\b",
    r"\bstarted buying\b",
]
NEGATIVE_FLAT_PATTERNS = [
    r"\bzero positions?\b",
    r"\bno positions?\b",
    r"\bflat\b",
]
NEGATIVE_SELL_PATTERNS = [
    r"\bsold\b",
    r"\btrimmed\b",
    r"\bclosed\b",
    r"\bout of\b",
]
WATCH_PATTERNS = [
    r"\bfavorites?\b",
    r"\bbullish\b",
    r"\bpromising\b",
    r"\blooks good\b",
]


def _stance_from_text(text: str) -> tuple[str, float, str]:
    lowered = text.lower()
    for pattern in NEGATIVE_FLAT_PATTERNS:
        if re.search(pattern, lowered):
            return "flat", 0.92, "明确说没有仓位"
    for pattern in NEGATIVE_SELL_PATTERNS:
        if re.search(pattern, lowered):
            return "sell", 0.85, "出现卖出/离场措辞"
    for pattern in POSITIVE_BUY_PATTERNS:
        if re.search(pattern, lowered):
            return "buy", 0.88, "出现买入/加仓措辞"
    for pattern in POSITIVE_HOLD_PATTERNS:
        if re.search(pattern, lowered):
            return "hold", 0.84, "出现持仓/仍持有措辞"
    for pattern in WATCH_PATTERNS:
        if re.search(pattern, lowered):
            return "watch", 0.62, "更像观点或偏好，不一定是仓位"
    return "watch", 0.45, "只检测到 ticker，没有足够仓位措辞"


def extract_claims_by_rules(posts: list[PostRecord]) -> list[PositionClaim]:
    claims: list[PositionClaim] = []
    for post in posts:
        tickers = sorted(set(TICKER_PATTERN.findall(post.title + " " + post.text)))
        if not tickers:
            continue
        stance, confidence, reason = _stance_from_text(f"{post.title}\n{post.text}")
        evidence = f"{reason} | {post.text[:220]}"
        for ticker in tickers:
            claims.append(
                PositionClaim(
                    post_id=post.post_id,
                    source=post.source,
                    author=post.author,
                    url=post.url,
                    ticker=ticker,
                    stance=stance,
                    confidence=confidence,
                    evidence=evidence,
                    published_at=post.published_at,
                    extractor="rules",
                )
            )
    return claims


def _extract_json_block(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def extract_claims_by_llm(posts: list[PostRecord], llm_config: dict[str, Any]) -> tuple[list[PositionClaim], str | None]:
    if not llm_config.get("enabled") or not llm_config.get("api_key"):
        return [], None

    payload_posts = [
        {
            "post_id": post.post_id,
            "source": post.source,
            "author": post.author,
            "url": post.url,
            "title": post.title,
            "text": post.text,
        }
        for post in posts[:20]
    ]
    prompt = (
        "You extract self-reported stock position claims from social posts.\n"
        "Return JSON only: an array of objects.\n"
        "Each object must contain: post_id, ticker, stance, confidence, evidence.\n"
        "stance must be one of: buy, hold, sell, flat, watch.\n"
        "Use hold only when the author strongly implies an existing position.\n"
        "Use flat when the author clearly says they have no position.\n"
        "Ignore posts without a ticker.\n"
        f"Posts:\n{json.dumps(payload_posts, ensure_ascii=False)}"
    )
    base_url = llm_config.get("base_url", "https://api.deepseek.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    body = {
        "model": llm_config.get("model", "deepseek-chat"),
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": "You are a careful financial text extraction engine."},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {llm_config['api_key']}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=45)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        raw_items = _extract_json_block(content)
        post_map = {post.post_id: post for post in posts}
        claims: list[PositionClaim] = []
        for item in raw_items:
            post = post_map.get(item.get("post_id", ""))
            if not post:
                continue
            ticker = str(item.get("ticker", "")).replace("$", "").upper().strip()
            if not ticker:
                continue
            claims.append(
                PositionClaim(
                    post_id=post.post_id,
                    source=post.source,
                    author=post.author,
                    url=post.url,
                    ticker=ticker,
                    stance=str(item.get("stance", "watch")).strip().lower(),
                    confidence=float(item.get("confidence", 0.5)),
                    evidence=str(item.get("evidence", ""))[:280],
                    published_at=post.published_at,
                    extractor="llm",
                )
            )
        return claims, None
    except Exception as exc:
        return [], f"LLM 抽取失败: {exc}"


def merge_claims(rule_claims: list[PositionClaim], llm_claims: list[PositionClaim]) -> list[PositionClaim]:
    merged: dict[tuple[str, str], PositionClaim] = {}
    for claim in rule_claims:
        merged[(claim.post_id, claim.ticker)] = claim
    for claim in llm_claims:
        key = (claim.post_id, claim.ticker)
        existing = merged.get(key)
        if existing is None or claim.confidence >= existing.confidence:
            merged[key] = claim
    return sorted(
        merged.values(),
        key=lambda item: (item.confidence, item.ticker, item.post_id),
        reverse=True,
    )
