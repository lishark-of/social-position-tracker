from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PostRecord:
    post_id: str
    source: str
    author: str
    url: str
    title: str
    text: str
    published_at: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PositionClaim:
    ticker: str
    original_ticker_text: str
    canonical_ticker: str
    action: str
    evidence: str
    confidence: float
    confidence_reason: str
    claim_type: str
    position_confidence: float
    is_position_disclosure: bool
    source: str
    source_url: str
    author: str
    published_at: str = ""
    captured_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
    raw_text: str = ""
    raw_text_hash: str = ""
    claim_hash: str = ""
    language: str = "unknown"
    post_id: str = ""
    extractor: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
