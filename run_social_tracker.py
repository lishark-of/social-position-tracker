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
    print(f"post_count={snapshot['post_count']}")
    print(f"claim_count={snapshot['claim_count']}")
    print(f"new_claim_count={snapshot.get('new_claim_count', 0)}")
    print(f"duplicate_claim_count={snapshot.get('duplicate_claim_count', 0)}")
    print(f"changed_opinion_count={snapshot.get('changed_opinion_count', 0)}")
    print(f"position_signal_count={snapshot.get('position_signal_count', 0)}")
    print(f"opinion_signal_count={snapshot.get('opinion_signal_count', 0)}")
    print(f"risk_signal_count={snapshot.get('risk_signal_count', 0)}")
    print(f"error_count={snapshot.get('error_count', len(snapshot.get('errors', [])))}")
    print(f"errors={json.dumps(snapshot.get('errors', []), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
