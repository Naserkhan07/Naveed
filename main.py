"""Start the links.txt Shorts/Reels automation."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 14):
    raise SystemExit(
        "Python 3.14 is not supported by the Chrome PO-token provider. "
        "Run: .\\.venv\\Scripts\\python.exe main.py"
    )

from dotenv import load_dotenv  # noqa: E402

from shorts_bot.file_queue import main as queue_main  # noqa: E402


def main() -> None:
    load_dotenv()
    queue_main()


if __name__ == "__main__":
    main()
