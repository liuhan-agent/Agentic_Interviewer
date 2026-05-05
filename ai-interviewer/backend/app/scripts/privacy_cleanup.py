from __future__ import annotations

import argparse
import json

from app.services.privacy_cleanup import cleanup_expired_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean expired interview privacy data.")
    parser.add_argument("--apply", action="store_true", help="Delete rows instead of dry-run.")
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args()

    report = cleanup_expired_data(
        dry_run=not args.apply,
        batch_size=args.batch_size,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
