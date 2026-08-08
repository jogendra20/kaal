#!/usr/bin/env python3
"""
Append a dated entry to DEVLOG.md.

Usage:
    python devlog.py "Wired kaal_decision into kaal_live_scanner.py"
    python devlog.py "Fixed rate limit bug" "Reduced poll interval to 15min"
"""
import sys
from datetime import datetime

LOG_FILE = "DEVLOG.md"


def main():
    if len(sys.argv) < 2:
        print("Usage: python devlog.py \"what you did\" [\"another line\"]")
        sys.exit(1)

    today = datetime.now().strftime("%Y-%m-%d")
    lines = sys.argv[1:]

    with open(LOG_FILE, "r") as f:
        content = f.read()

    header = f"### {today}"
    entry_lines = "\n".join(f"- {line}" for line in lines)

    if header in content:
        content = content.replace(header, f"{header}\n{entry_lines}", 1)
    else:
        content = content.rstrip() + f"\n\n{header}\n{entry_lines}\n"

    with open(LOG_FILE, "w") as f:
        f.write(content)

    print(f"Logged to {LOG_FILE} under {today}:")
    for line in lines:
        print(f"  - {line}")


if __name__ == "__main__":
    main()
