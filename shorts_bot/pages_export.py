"""Export the status dashboard as a static site (used for GitHub Pages).

The same dashboard that runs on localhost is written to a folder as plain
static files — ``index.html`` plus ``api/status.json`` — so the cloud
autopilot can publish it to GitHub Pages after every run. That makes the
"what, when, where" view available on the web, permanently online, without
anything running on your own PC.

Usage: ``python -m shorts_bot.pages_export --out site``
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .db import JobRepository
from .status_panel import _INDEX_HTML, build_status


def export_pages_site(
    settings: Settings,
    repository: JobRepository,
    output_dir: Path,
) -> Path:
    """Write the static dashboard tree and return the index path."""
    output_dir = Path(output_dir)
    api_dir = output_dir / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build_status(settings, repository), indent=1)
    (api_dir / "status.json").write_text(payload + "\n", encoding="utf-8")
    index = output_dir / "index.html"
    index.write_text(_INDEX_HTML, encoding="utf-8")
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="site", help="Output directory (default: site)")
    args = parser.parse_args()
    settings = Settings.from_env()
    repository = JobRepository(settings.database_path)
    index = export_pages_site(settings, repository, Path(args.out))
    print(f"Static status site written to {index}", flush=True)


if __name__ == "__main__":
    main()
