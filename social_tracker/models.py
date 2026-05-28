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
    post_id: str
    source: str
    author: str
    url: str
    ticker: str
    stance: str
    confidence: float
    evidence: str
    published_at: str = ""
    extractor: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
