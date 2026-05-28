from __future__ import annotations

from datetime import datetime
from typing import Any

from .collectors import collect_all
from .extractors import extract_claims_by_llm, extract_claims_by_rules, merge_claims
from .storage import append_snapshot, resolve_llm_config


def run_pipeline(config: dict[str, Any]) -> dict[str, Any]:
    posts, errors = collect_all(config)
    rule_claims = extract_claims_by_rules(posts)
    llm_claims, llm_error = extract_claims_by_llm(posts, resolve_llm_config(config.get("llm", {})))
    if llm_error:
        errors.append(llm_error)
    merged_claims = merge_claims(rule_claims, llm_claims)
    snapshot = {
        "target_name": config.get("target_name", ""),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "post_count": len(posts),
        "claim_count": len(merged_claims),
        "errors": errors,
        "posts": [post.to_dict() for post in posts],
        "claims": [claim.to_dict() for claim in merged_claims],
    }
    append_snapshot(snapshot)
    return snapshot
