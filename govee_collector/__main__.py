"""CLI entry point: `python3 -m govee_collector`."""

from __future__ import annotations

import asyncio
import logging
import sys

from govee_collector.collector import run


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
