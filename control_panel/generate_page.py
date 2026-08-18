"""CLI entry point: writes the control panel's static HTML shell.

Unlike the other three pages' generate scripts, this is **not** meant to
run on cron -- there's no data snapshot baked into the page (see
render.py's docstring), so nothing about the output ever changes between
runs. Run once at deploy time, and again only if render.py itself
changes.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from control_panel.render import render_html


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.rename(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    _atomic_write(args.output_dir / "index.html", render_html())
    print(f"Wrote {args.output_dir}/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
