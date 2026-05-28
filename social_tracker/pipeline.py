from __future__ import annotations

from datetime import datetime
from typing import Any

from .claim_utils import compare_latest_claims, flatten_claims_from_snapshots, is_post_relevant_to_handle
from .collectors import collect_all
from .extractors import extract_claims_by_llm, extract_claims_by_rules, merge_claims
from .storage import append_snapshot, load_snapshots, resolve_llm_config


def run_pipeline(config: dict[str, Any]) -> dict[str, Any]:
    existing_snapshots = load_snapshots()
    existing_claims = flatten_claims_from_snapshots(existing_snapshots, dedupe=True)
    existing_hashes = {claim["claim_hash"] for claim in existing_claims}
    posts, errors = collect_all(config)
    focus_handle = config.get("focus_handle", "")
    focus_aliases = config.get("focus_aliases", [])
    focus_domain = config.get("focus_domain", "")
    focus_direct_url = config.get("focus_direct_url", "")
    if focus_handle or focus_aliases or focus_domain or focus_direct_url:
        posts = [
            post
            for post in posts
            if is_post_relevant_to_handle(
                post.url,
                f"{post.title}\n{post.text}".strip(),
                post.author,
                focus_handle,
                focus_aliases=focus_aliases,
                focus_domain=focus_domain,
                focus_direct_url=focus_direct_url,
            )
        ]
    rule_claims = extract_claims_by_rules(posts)
    llm_claims, llm_error = extract_claims_by_llm(posts, resolve_llm_config(config.get("llm", {})))
    if llm_error:
        errors.append(llm_error)
    merged_claims = merge_claims(rule_claims, llm_claims)
    normalized_claims = [claim.to_dict() for claim in merged_claims]
    new_claims = [claim for claim in normalized_claims if claim["claim_hash"] not in existing_hashes]
    duplicate_claim_count = len(normalized_claims) - len(new_claims)
    claim_changes = compare_latest_claims(existing_claims, new_claims)
    changed_opinion_count = sum(1 for item in claim_changes if item["change_type"] in {"upgraded", "downgraded"})
    snapshot = {
        "target_name": config.get("target_name", ""),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "post_count": len(posts),
        "claim_count": len(normalized_claims),
        "new_claim_count": len(new_claims),
        "duplicate_claim_count": duplicate_claim_count,
        "changed_opinion_count": changed_opinion_count,
        "position_signal_count": sum(1 for claim in new_claims if claim["claim_type"] == "position_signal"),
        "opinion_signal_count": sum(1 for claim in new_claims if claim["claim_type"] == "opinion_signal"),
        "risk_signal_count": sum(1 for claim in new_claims if claim["claim_type"] == "risk_signal"),
        "error_count": len(errors),
        "errors": errors,
        "posts": [post.to_dict() for post in posts],
        "claims": new_claims,
        "claim_changes": claim_changes,
    }
    append_snapshot(snapshot)
    return snapshot
