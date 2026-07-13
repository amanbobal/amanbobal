#!/usr/bin/env python3
"""Pick which profile README to show and write the root README.md."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".github" / "profile-state"
PROFILES = {
    "current": ROOT / "profiles" / "current.md",
    "neofetch": ROOT / "profiles" / "neofetch.md",
}


def read_state() -> str:
    if STATE_FILE.exists():
        value = STATE_FILE.read_text(encoding="utf-8").strip()
        if value in PROFILES:
            return value
    return "current"


def profile_for_run(force: str | None = None, rotate: bool = True) -> str:
    if force in PROFILES:
        return force

    if not rotate:
        return read_state()

    slot = datetime.now(timezone.utc).hour // 6
    return "neofetch" if slot % 2 else "current"


def write_readme(profile: str) -> None:
    content = PROFILES[profile].read_text(encoding="utf-8")
    (ROOT / "README.md").write_text(content, encoding="utf-8")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(profile + "\n", encoding="utf-8")
    print(f"Active profile: {profile}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the selected profile without writing README.md",
    )
    args = parser.parse_args()

    force = os.environ.get("FORCE_PROFILE", "").strip() or None
    rotate = os.environ.get("ROTATE_PROFILE", "true").lower() != "false"
    selected = profile_for_run(force=force, rotate=rotate)

    if args.print_only:
        print(selected)
        return 0

    write_readme(selected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
