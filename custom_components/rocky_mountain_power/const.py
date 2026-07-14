"""Constants for the Rocky Mountain Power integration."""

from datetime import timedelta
import logging

DOMAIN = "rocky_mountain_power"
LOGGER = logging.getLogger(__package__)

# --- Site / endpoints ---
BASE_URL = "https://csapps.rockymountainpower.net"
LOGIN_URL = f"{BASE_URL}/oauth2/authorization/B2C_1A_PAC_SIGNIN"
OAUTH_CALLBACK_PREFIX = f"{BASE_URL}/login/oauth2/code/"

B2C_TENANT = "bheb2c.onmicrosoft.com"
B2C_POLICY = "B2C_1A_PAC_signin"
B2C_LOGIN_HOST = "login.csapps.rockymountainpower.net"
B2C_POLICY_BASE = f"https://{B2C_LOGIN_HOST}/{B2C_TENANT}/{B2C_POLICY}"
B2C_SELF_ASSERTED_URL = f"{B2C_POLICY_BASE}/SelfAsserted"
B2C_CONFIRMED_URL = f"{B2C_POLICY_BASE}/api/CombinedSigninAndSignup/confirmed"

API_GET_ACCOUNT_LIST = f"{BASE_URL}/api/self-service/getAccountList"
API_GET_METERED_AGREEMENTS = f"{BASE_URL}/api/account/getMeteredAgreements"
API_GET_INTERVAL_USAGE = f"{BASE_URL}/api/energy-usage/getIntervalUsageForDate"
HANDSHAKE_URL = f"{BASE_URL}/idm/handshake"
# The Angular app's own shell page (unauthenticated-accessible) -- this is
# where the `main.<hash>.js` bundle reference actually lives, not the B2C
# login page (which is Microsoft's own Identity Experience Framework UI and
# references none of RMP's own JS).
APP_SHELL_URL = f"{BASE_URL}/idm/login"

PACIFICORP_SUBSIDIARY = "RockyMountainPower"
# The interval-usage endpoint requires a registerType the frontend never
# reads back from any account-resolution response -- it's a fixed value for
# single-register residential AMI meters, confirmed against the live API.
REGISTER_TYPE = "01"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# --- Request-body encryption (confirmed live against the real API) ---
# Every POST body (except the handshake itself and B2C login) must be
# RSA-signed and AES-GCM encrypted client-side -- session cookies alone are
# not sufficient. See api.py's RockyMountainPowerCrypto for the handshake
# and per-request encryption implementation.
CRYPTO_RSA_KEY_SIZE = 4096
CRYPTO_RSA_PUBLIC_EXPONENT = 65537
CRYPTO_HASH_ALG = "SHA-256"  # maps to hashes.SHA256() throughout
CRYPTO_AES_IV_LENGTH = 12  # bytes; AES-GCM standard nonce size
CRYPTO_SIGNATURE_HEADER = "X-WCSSS-Content-Signature"
CRYPTO_POLICY_HEADER = "X-WCSSS-Policy"
CRYPTO_POLICY_NONSECURE = "0"  # sent only on the handshake call itself
XSRF_COOKIE_NAME = "XSRF-TOKEN"
XSRF_HEADER_NAME = "X-XSRF-TOKEN"

# --- Behavior ---
# RMP's interval data lags roughly a day; polling faster than this is pointless.
UPDATE_INTERVAL = timedelta(hours=24)
# Re-pull this many trailing days each cycle to catch late-corrected readings.
LOOKBACK_DAYS = 3
# Treat a login as good for this long before proactively refreshing it,
# independent of any reactive (failure-triggered) invalidation.
SESSION_MAX_AGE = timedelta(hours=6)

STATISTIC_ID = f"{DOMAIN}:energy_consumption"
STATISTIC_NAME = "Rocky Mountain Power Energy Consumption"

ARCHIVE_DIR_NAME = "rocky_mountain_power_archive"
