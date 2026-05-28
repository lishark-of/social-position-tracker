from __future__ import annotations

import json
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from social_tracker.pipeline import run_pipeline
from social_tracker.storage import load_config


def main() -> None:
    config = load_config()
    snapshot = run_pipeline(config)
    print(
        json.dumps(
            {
                "ran_at": snapshot["ran_at"],
                "post_count": snapshot["post_count"],
                "claim_count": snapshot["claim_count"],
                "errors": snapshot["errors"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
