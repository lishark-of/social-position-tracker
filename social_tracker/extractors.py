from __future__ import annotations

import json
from typing import Any

import requests

from .claim_utils import (
    build_claim_hash,
    classify_signal,
    detect_language,
    extract_ticker_mentions,
    infer_canonical_ticker,
    normalize_claim_dict,
    normalize_source,
    select_evidence,
    sha256_text,
)
from .models import PositionClaim, PostRecord


def extract_claims_by_rules(posts: list[PostRecord]) -> list[PositionClaim]:
    claims: list[PositionClaim] = []
    for post in posts:
        raw_text = f"{post.title}\n{post.text}".strip()
        mentions = extract_ticker_mentions(raw_text)
        if not mentions:
            continue
        language = detect_language(raw_text)
        raw_text_hash = sha256_text(raw_text)
        for mention in mentions:
            evidence = select_evidence(raw_text, mention["original_ticker_text"])
            signal = classify_signal(evidence, raw_text)
            canonical_ticker = mention["canonical_ticker"] or infer_canonical_ticker(mention["original_ticker_text"])
            claims.append(
                PositionClaim(
                    ticker=canonical_ticker,
                    original_ticker_text=mention["original_ticker_text"],
                    canonical_ticker=canonical_ticker,
                    action=signal["action"],
                    evidence=evidence,
                    confidence=signal["confidence"],
                    confidence_reason=signal["confidence_reason"],
                    claim_type=signal["claim_type"],
                    position_confidence=signal["position_confidence"],
                    is_position_disclosure=signal["is_position_disclosure"],
                    source=normalize_source(post.source),
                    source_url=post.url,
                    author=post.author,
                    published_at=post.published_at,
                    captured_at=post.fetched_at,
                    raw_text=raw_text,
                    raw_text_hash=raw_text_hash,
                    claim_hash=build_claim_hash(canonical_ticker, signal["action"], evidence, post.url, raw_text_hash),
                    language=language,
                    post_id=post.post_id,
                    extractor="rules",
                )
            )
    return claims


def _extract_json_block(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
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
        "You extract conservative public investment signals from social posts.\n"
        "Return JSON only: an array of objects.\n"
        "Each object must contain: post_id, original_ticker_text, action, evidence, confidence, confidence_reason, claim_type, position_confidence, is_position_disclosure.\n"
        "action must be one of: 买入, 持有, 卖出, 空仓, 观察.\n"
        "claim_type must be one of: position_signal, opinion_signal, risk_signal, unknown.\n"
        "Be conservative. Do not convert opinion into real position disclosure.\n"
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
            raw_text = f"{post.title}\n{post.text}".strip()
            original_ticker_text = str(item.get("original_ticker_text", "")).strip().replace("$", "")
            canonical_ticker = infer_canonical_ticker(original_ticker_text)
            if not canonical_ticker:
                continue
            raw_claim = {
                "ticker": canonical_ticker,
                "original_ticker_text": original_ticker_text,
                "canonical_ticker": canonical_ticker,
                "action": str(item.get("action", "观察")).strip() or "观察",
                "evidence": str(item.get("evidence", ""))[:280],
                "confidence": float(item.get("confidence", 0.5)),
                "confidence_reason": str(item.get("confidence_reason", "")),
                "claim_type": str(item.get("claim_type", "unknown")).strip() or "unknown",
                "position_confidence": float(item.get("position_confidence", 0.0)),
                "is_position_disclosure": bool(item.get("is_position_disclosure", False)),
                "source": normalize_source(post.source),
                "source_url": post.url,
                "author": post.author,
                "published_at": post.published_at,
                "captured_at": post.fetched_at,
                "raw_text": raw_text,
                "language": detect_language(raw_text),
                "post_id": post.post_id,
                "extractor": "llm",
            }
            normalized = normalize_claim_dict(raw_claim, fallback_captured_at=post.fetched_at)
            claims.append(PositionClaim(**normalized))
        return merge_claims([], claims), None
    except Exception as exc:
        return [], f"LLM 抽取失败: {exc}"


def merge_claims(rule_claims: list[PositionClaim], llm_claims: list[PositionClaim]) -> list[PositionClaim]:
    merged: dict[str, PositionClaim] = {}
    for claim in rule_claims:
        merged[claim.claim_hash] = claim
    for claim in llm_claims:
        existing = merged.get(claim.claim_hash)
        if existing is None or claim.confidence >= existing.confidence:
            merged[claim.claim_hash] = claim
    return sorted(
        merged.values(),
        key=lambda item: (item.confidence, item.canonical_ticker, item.captured_at),
        reverse=True,
    )
