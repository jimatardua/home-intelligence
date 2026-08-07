"""CLI entry point: generates the cigar-storage dashboard (index.html + data.json).

Meant to run every 2 minutes via cron -- cheap enough (pure local recorder DB
reads, no external API calls) to run that often; the client-side page
refetches `data.json` on its own 60-second cadence in between runs.
"""

from __future__ import annotations

import argparse
import datetime as dt_module
import os
import sys
from pathlib import Path

from cigar_dashboard.govee_history import get_current_readings, get_humidity_history, get_temp_history
from cigar_dashboard.render import DashboardContext, render_data_json, render_html
from energy_report.ha_recorder import open_recorder_db


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.rename(tmp, path)


def _build_context(db_path: Path) -> DashboardContext:
    now_local = dt_module.datetime.now().astimezone()
    conn = open_recorder_db(db_path)

    return DashboardContext(
        generated_at=now_local,
        readings=get_current_readings(conn),
        humidity_history=get_humidity_history(conn, now_local),
        temp_history=get_temp_history(conn, now_local),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    ctx = _build_context(args.db_path)
    _atomic_write(args.output_dir / "index.html", render_html(ctx))
    _atomic_write(args.output_dir / "data.json", render_data_json(ctx))
    print(f"Wrote {args.output_dir}/index.html and data.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
