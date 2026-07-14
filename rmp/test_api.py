#!/usr/bin/env python3
"""Exercise the real custom_components/rocky_mountain_power/api.py module
end-to-end against the live API, using the same .env credentials as
poc_encrypted_client.py. This is a one-off dev verification script, not
part of the HA integration itself.

api.py is deliberately synchronous (see its module docstring for why); this
script calls it directly, mirroring how coordinator.py/config_flow.py will
dispatch it via hass.async_add_executor_job.

    .venv/bin/python test_api.py
"""

import getpass
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from custom_components.rocky_mountain_power import api  # noqa: E402

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")


def main() -> None:
    load_dotenv()
    username = os.environ.get("RMP_USERNAME", "").strip() or input("RMP username: ").strip()
    password = os.environ.get("RMP_PASSWORD", "") or getpass.getpass("RMP password (hidden): ")

    client = api.RockyMountainPowerClient(username, password)
    try:
        agreement = client.get_metered_agreements()
        print(f"\nResolved agreement (values withheld): {type(agreement).__name__} ok")
        print(f"site_bundle_signature: {client.site_bundle_signature}")
        print(f"is_authenticated: {client.is_authenticated}")

        yesterday = date.today() - timedelta(days=1)
        readings = client.get_interval_usage(yesterday)
        print(f"\n{len(readings)} interval readings for {yesterday.isoformat()}:")
        for r in readings:
            print(f"  {r['readTime']}  {r['usage']} kWh")

        print("\ncalling get_metered_agreements again (should hit cache, no new HTTP calls logged)")
        client.get_metered_agreements()
    finally:
        client.close()


if __name__ == "__main__":
    main()
