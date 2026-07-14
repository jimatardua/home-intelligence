"""Client for Rocky Mountain Power's csapps.rockymountainpower.net portal.

This talks directly to the same backend the Angular SPA uses. Two layers of
protection have to be replicated:

1. Session auth: an Azure AD B2C ("self-asserted" custom policy) login flow,
   ending in a session cookie on csapps.rockymountainpower.net.
2. Request-body encryption: independent of the session cookie, every POST
   body (other than the B2C login itself and the handshake below) must be
   RSA-signed and AES-GCM encrypted. This was reverse-engineered from the
   site's own JS bundles and confirmed live:

   - Client generates two RSA-4096/SHA-256 keypairs: one for signing
     (RSASSA-PKCS1-v1_5), one for key exchange (RSA-OAEP).
   - POST both public keys (SPKI, base64, joined with ":") to
     `/idm/handshake`. The server responds with an AES-256 key, RSA-OAEP
     encrypted under the client's own OAEP public key.
   - Per request: sign the plaintext JSON body (PKCS1v15/SHA-256) with the
     client's signing private key -> base64 -> `X-WCSSS-Content-Signature`
     header. AES-256-GCM encrypt the same plaintext with a random 12-byte
     IV, tagLength 128 -> body becomes base64(iv) + base64(ciphertext+tag).
   - Responses are plain JSON, not encrypted.
   - Every mutating request also needs `X-XSRF-TOKEN` (Angular's default
     double-submit CSRF header, read from the `XSRF-TOKEN` cookie) or the
     backend silently serves the SPA shell instead of a real API response.

Deliberately synchronous, using `requests`, not `aiohttp`: RMP sits behind a
WAF (the `TS...` cookies are the standard F5/Akamai bot-defense naming
convention) that appears to fingerprint the TLS ClientHello. In side-by-side
testing, `aiohttp` was rejected with a bare HTTP 400 at the SelfAsserted
login step 100% of the time, while `requests` succeeded 100% of the time,
from the same machine/account, back to back -- with byte-identical request
headers/body confirmed against a neutral echo endpoint. That points at the
TLS layer, not application logic, and Python's `ssl` module gives no
practical control over the ClientHello details that drive TLS fingerprinting
for aiohttp's asyncio SSL transport. Rather than chase that, this client
stays synchronous and is dispatched via `hass.async_add_executor_job` from
coordinator.py/config_flow.py, matching the standard HA pattern for wrapping
a non-async library.

Both auth layers (session + crypto handshake) are established together at
login and treated as one unit: `ensure_authenticated()` is the single gate
every public method calls before doing anything else. Any caller that hits
a session or crypto failure calls `_invalidate_session()`, which forces a
fresh login (and fresh handshake) on the *next* call -- there is no in-call
retry loop by design, so failures surface immediately and self-heal on the
next poll.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime
import json
import re
import secrets
from urllib.parse import urlencode

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .const import (
    API_GET_ACCOUNT_LIST,
    API_GET_INTERVAL_USAGE,
    API_GET_METERED_AGREEMENTS,
    APP_SHELL_URL,
    B2C_POLICY,
    B2C_POLICY_BASE,
    CRYPTO_AES_IV_LENGTH,
    CRYPTO_POLICY_HEADER,
    CRYPTO_POLICY_NONSECURE,
    CRYPTO_RSA_KEY_SIZE,
    CRYPTO_RSA_PUBLIC_EXPONENT,
    CRYPTO_SIGNATURE_HEADER,
    HANDSHAKE_URL,
    LOGGER,
    LOGIN_URL,
    PACIFICORP_SUBSIDIARY,
    REGISTER_TYPE,
    SESSION_MAX_AGE,
    USER_AGENT,
    XSRF_COOKIE_NAME,
    XSRF_HEADER_NAME,
)

SETTINGS_RE = re.compile(r"var SETTINGS = (\{.*?\});", re.DOTALL)
BUNDLE_SIGNATURE_RE = re.compile(r"main\.[0-9a-f]+\.js")


class RockyMountainPowerError(Exception):
    """Base error for all Rocky Mountain Power API failures."""


class CannotConnect(RockyMountainPowerError):
    """Network-level failure talking to the portal."""


class InvalidAuth(RockyMountainPowerError):
    """Login failed -- bad username/password."""


class UnexpectedResponse(RockyMountainPowerError):
    """Portal responded, but not in a shape we understand.

    Also raised when a request that should have returned encrypted-channel
    JSON instead got the SPA's HTML shell back -- the standard symptom of a
    missing/expired session or a missing XSRF header.
    """


def parse_settings(html: str) -> dict:
    """Extract the `var SETTINGS = {...}` blob from a B2C login page.

    Isolated on its own so that if RMP changes their login page markup,
    there is exactly one place to fix.
    """
    match = SETTINGS_RE.search(html)
    if not match:
        raise UnexpectedResponse("Could not find SETTINGS blob in B2C login page HTML")
    return json.loads(match.group(1))


@dataclass
class MeteredAgreement:
    """Identifiers needed to request interval usage for one meter."""

    site_idn: int
    register_type: str
    service_sequence: int
    account_sequence: int
    agreement_sequence: int
    customer_idn: int


@dataclass
class _CryptoState:
    sign_key: RSAPrivateKey
    aes_key: bytes


@dataclass
class _AuthState:
    authenticated: bool = False
    logged_in_at: datetime | None = None
    force_relogin: bool = False
    site_bundle_signature: str | None = None


def _oaep_padding() -> padding.OAEP:
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
    )


class RockyMountainPowerClient:
    """Synchronous client for the RMP customer portal API.

    Every method here is a plain blocking call. Callers (coordinator.py,
    config_flow.py) are responsible for dispatching to a worker thread via
    `hass.async_add_executor_job` -- see the module docstring for why this
    isn't natively async.
    """

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        # Private session: this integration's cookies must never mix with
        # another integration's usage.
        self._session = requests.Session()
        self._auth = _AuthState()
        self._crypto: _CryptoState | None = None
        self._cached_agreement: MeteredAgreement | None = None

    def close(self) -> None:
        self._session.close()

    @property
    def is_authenticated(self) -> bool:
        return self._auth.authenticated

    @property
    def site_bundle_signature(self) -> str | None:
        return self._auth.site_bundle_signature

    @property
    def last_login_at(self) -> datetime | None:
        return self._auth.logged_in_at

    @property
    def cached_agreement(self) -> MeteredAgreement | None:
        return self._cached_agreement

    def _invalidate_session(self) -> None:
        LOGGER.debug("Invalidating session; next call will force a fresh login")
        self._auth.force_relogin = True

    def ensure_authenticated(self) -> None:
        """Gate every public API call. Logs in only if actually needed."""
        if self._auth.force_relogin:
            LOGGER.debug("Session marked invalid, logging in")
            self._login()
            return

        if not self._auth.authenticated:
            LOGGER.debug("No active session, logging in")
            self._login()
            return

        assert self._auth.logged_in_at is not None
        age = datetime.utcnow() - self._auth.logged_in_at
        if age > SESSION_MAX_AGE:
            LOGGER.debug("Session age %s exceeds max age %s, refreshing", age, SESSION_MAX_AGE)
            self._login()
            return

        LOGGER.debug("Session still valid (age %s), reusing", age)

    def _login(self) -> None:
        LOGGER.debug("Starting B2C login flow for %s", self._username)
        try:
            r = self._session.get(LOGIN_URL, headers={"User-Agent": USER_AGENT})
            if r.status_code != 200:
                raise CannotConnect(f"GET login page returned HTTP {r.status_code}")

            settings = parse_settings(r.text)
            csrf = settings["csrf"]
            trans_id = settings["transId"]
            LOGGER.debug("Parsed SETTINGS blob from B2C login page")

            LOGGER.debug("Submitting credentials to SelfAsserted endpoint")
            form_body = urlencode(
                {
                    "request_type": "RESPONSE",
                    "signInName": self._username,
                    "password": self._password,
                }
            )
            r = self._session.post(
                f"{B2C_POLICY_BASE}/SelfAsserted",
                params={"tx": trans_id, "p": B2C_POLICY},
                headers={
                    "X-CSRF-TOKEN": csrf,
                    "User-Agent": USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=form_body,
            )
            if r.status_code != 200:
                LOGGER.debug("SelfAsserted error body: %s", r.text[:500])
                raise InvalidAuth(f"SelfAsserted returned HTTP {r.status_code}")
            try:
                body = r.json()
                status = body.get("status") if isinstance(body, dict) else None
                if status is not None and str(status) != "200":
                    raise InvalidAuth(f"SelfAsserted rejected credentials: {body}")
            except ValueError:
                # Non-JSON body is fine here; the redirect-chain check
                # below is the authoritative success signal.
                pass

            LOGGER.debug("Following confirmed -> oauth2/code redirect chain")
            r = self._session.get(
                f"{B2C_POLICY_BASE}/api/CombinedSigninAndSignup/confirmed",
                params={
                    "rememberMe": "false",
                    "csrf_token": csrf,
                    "tx": trans_id,
                    "p": B2C_POLICY,
                },
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code != 200:
                raise InvalidAuth(f"confirmed redirect chain returned HTTP {r.status_code}")
            if "oauth2/code" not in r.url:
                raise InvalidAuth(f"Did not land on oauth2/code callback; final URL: {r.url.split('?')[0]}")

            LOGGER.debug("Login successful, performing crypto handshake")
            self._crypto = self._handshake()
            self._auth.site_bundle_signature = self._fetch_bundle_signature()

            self._auth.authenticated = True
            self._auth.logged_in_at = datetime.utcnow()
            self._auth.force_relogin = False
            self._cached_agreement = None  # re-resolve under the new session
            LOGGER.info("Rocky Mountain Power login successful")
        except InvalidAuth:
            self._auth.authenticated = False
            raise
        except requests.RequestException as err:
            self._auth.authenticated = False
            raise CannotConnect(f"Network error during login: {err}") from err

    def _fetch_bundle_signature(self) -> str | None:
        """Best-effort fetch of RMP's frontend JS bundle hash.

        Diagnostics-only canary: if this changes between polls, RMP shipped
        a new frontend build, which is exactly the kind of change that could
        silently break parse_settings() or the request-encryption contract.
        Never allowed to fail login over -- if the app shell page changes
        shape, we just lose the canary, not functionality.
        """
        try:
            r = self._session.get(APP_SHELL_URL, headers={"User-Agent": USER_AGENT})
            if r.status_code != 200:
                LOGGER.debug("Bundle signature fetch got HTTP %d, skipping", r.status_code)
                return None
            match = BUNDLE_SIGNATURE_RE.search(r.text)
            signature = match.group(0) if match else None
            LOGGER.debug("site_bundle_signature=%s", signature)
            return signature
        except requests.RequestException as err:
            LOGGER.debug("Bundle signature fetch failed, skipping: %s", err)
            return None

    def _handshake(self) -> _CryptoState:
        LOGGER.debug("Generating RSA-4096 handshake keypairs (a few seconds)")
        sign_key = rsa.generate_private_key(
            public_exponent=CRYPTO_RSA_PUBLIC_EXPONENT, key_size=CRYPTO_RSA_KEY_SIZE
        )
        enc_key = rsa.generate_private_key(
            public_exponent=CRYPTO_RSA_PUBLIC_EXPONENT, key_size=CRYPTO_RSA_KEY_SIZE
        )

        sign_pub_spki = sign_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        enc_pub_spki = enc_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        handshake_body = (
            base64.b64encode(sign_pub_spki).decode()
            + ":"
            + base64.b64encode(enc_pub_spki).decode()
        )

        headers = {
            "Content-Type": "application/octet-stream",
            CRYPTO_POLICY_HEADER: CRYPTO_POLICY_NONSECURE,
            "User-Agent": USER_AGENT,
        }
        headers.update(self._xsrf_headers())

        LOGGER.debug("POST /idm/handshake")
        r = self._session.post(HANDSHAKE_URL, data=handshake_body, headers=headers)
        if r.status_code != 200:
            raise UnexpectedResponse(f"/idm/handshake returned HTTP {r.status_code}")

        raw_text = r.text.strip()
        try:
            wrapped_key = base64.b64decode(raw_text)
        except Exception as err:
            raise UnexpectedResponse(f"/idm/handshake response is not valid base64: {err}") from err

        expected_len = CRYPTO_RSA_KEY_SIZE // 8
        if len(wrapped_key) != expected_len:
            raise UnexpectedResponse(
                f"/idm/handshake response was {len(wrapped_key)} bytes, expected {expected_len} "
                "-- this usually means the session/XSRF token was rejected and the SPA shell "
                "was returned instead of the real endpoint"
            )

        aes_key = enc_key.decrypt(wrapped_key, _oaep_padding())
        LOGGER.debug("Handshake complete; derived AES key length=%d bytes", len(aes_key))
        return _CryptoState(sign_key=sign_key, aes_key=aes_key)

    def _xsrf_headers(self) -> dict[str, str]:
        token = self._session.cookies.get(XSRF_COOKIE_NAME, domain="csapps.rockymountainpower.net")
        if token is None:
            token = self._session.cookies.get(XSRF_COOKIE_NAME)
        if token is None:
            LOGGER.debug("No %s cookie present yet", XSRF_COOKIE_NAME)
            return {}
        return {XSRF_HEADER_NAME: token}

    def _encrypt_body(self, payload: dict) -> tuple[str, dict[str, str]]:
        assert self._crypto is not None
        plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = self._crypto.sign_key.sign(plaintext, padding.PKCS1v15(), hashes.SHA256())
        iv = secrets.token_bytes(CRYPTO_AES_IV_LENGTH)
        ciphertext = AESGCM(self._crypto.aes_key).encrypt(iv, plaintext, None)
        body = base64.b64encode(iv).decode() + base64.b64encode(ciphertext).decode()
        headers = {
            "Content-Type": "application/json",
            CRYPTO_SIGNATURE_HEADER: base64.b64encode(signature).decode(),
        }
        return body, headers

    def _secure_post(self, url: str, payload: dict) -> dict:
        """POST an encrypted+signed body to `url`, returning parsed JSON.

        Detects the "got the SPA shell back" failure mode (missing/expired
        XSRF or session) and invalidates the session so the *next* call
        re-authenticates, rather than retrying inline here.
        """
        body, headers = self._encrypt_body(payload)
        headers["User-Agent"] = USER_AGENT
        headers.update(self._xsrf_headers())

        try:
            r = self._session.post(url, data=body, headers=headers)
            LOGGER.debug("POST %s -> HTTP %d", url, r.status_code)
            if r.status_code != 200:
                self._invalidate_session()
                raise UnexpectedResponse(f"POST {url} returned HTTP {r.status_code}")
            try:
                return r.json()
            except ValueError as err:
                self._invalidate_session()
                raise UnexpectedResponse(
                    f"POST {url} did not return JSON -- session/XSRF likely expired"
                ) from err
        except requests.RequestException as err:
            raise CannotConnect(f"Network error on POST {url}: {err}") from err

    def get_metered_agreements(self, *, force_refresh: bool = False) -> MeteredAgreement:
        """Resolve (and cache) the account/meter identifiers for this login."""
        self.ensure_authenticated()

        if self._cached_agreement is not None and not force_refresh:
            LOGGER.debug("Using cached metered agreement")
            return self._cached_agreement

        LOGGER.debug("Resolving account list")
        account_list_resp = self._secure_post(
            API_GET_ACCOUNT_LIST,
            {
                "getAccountListRequestBody": {
                    "request": {"webUserID": self._username},
                    "domain": {"pacifiCorpSubsidiary": PACIFICORP_SUBSIDIARY},
                }
            },
        )
        try:
            accounts = account_list_resp["getAccountListResponseBody"]["accountList"]["webAccount"]
            account = accounts[0]
            customer_idn = account["customer"]["idn"]
            account_sequence = account["sequence"]
        except (KeyError, IndexError, TypeError) as err:
            raise UnexpectedResponse(f"Unexpected getAccountList response shape: {account_list_resp}") from err

        LOGGER.debug("Resolving metered agreements")
        agreements_resp = self._secure_post(
            API_GET_METERED_AGREEMENTS,
            {
                "getMeteredAgreementsRequestBody": {
                    "agreementRequest": {
                        "customerIDN": customer_idn,
                        "accountSequence": account_sequence,
                    },
                    "source": None,
                }
            },
        )
        try:
            agreement = agreements_resp["getMeteredAgreementsResponseBody"]["meteredAgreementList"][
                "meteredAgreement"
            ][0]
            self._cached_agreement = MeteredAgreement(
                site_idn=agreement["siteIDN"],
                register_type=REGISTER_TYPE,
                service_sequence=agreement["serviceSequence"],
                account_sequence=agreement["accountSequence"],
                agreement_sequence=agreement["agreementSequence"],
                customer_idn=agreement["customerIDN"],
            )
        except (KeyError, IndexError, TypeError) as err:
            raise UnexpectedResponse(f"Unexpected getMeteredAgreements response shape: {agreements_resp}") from err

        LOGGER.debug("Resolved and cached metered agreement (siteIDN redacted)")
        return self._cached_agreement

    def get_interval_usage(self, target_date: date) -> list[dict]:
        """Return hourly interval readings for `target_date`.

        Each item is `{"readDate": "YYYY-MM-DD", "readTime": "HH:00", "usage": "<kWh str>"}`.
        `readTime` is hour-ending (e.g. "03:00" covers 02:00-03:00, and
        "24:00" covers 23:00-24:00 of the *same* readDate).

        Returns an empty list if RMP has no data for that date yet (common
        for "yesterday" queried too early, or dates before meter install).
        """
        self.ensure_authenticated()
        agreement = self.get_metered_agreements()

        LOGGER.debug("Requesting interval usage for %s", target_date.isoformat())
        resp = self._secure_post(
            API_GET_INTERVAL_USAGE,
            {
                "getIntervalUsageForDateRequestBody": {
                    "request": {
                        "siteIDN": agreement.site_idn,
                        "registerType": agreement.register_type,
                        "serviceSequence": agreement.service_sequence,
                        "readDate": target_date.isoformat(),
                        "agreement": {
                            "customerIDN": agreement.customer_idn,
                            "accountSequence": agreement.account_sequence,
                            "agreementSequence": agreement.agreement_sequence,
                        },
                    }
                }
            },
        )
        try:
            body = resp["getIntervalUsageForDateResponseBody"]
        except (KeyError, TypeError) as err:
            raise UnexpectedResponse(f"Unexpected getIntervalUsageForDate response shape: {resp}") from err

        if not body.get("intervalDataExists") or body.get("response") is None:
            LOGGER.debug("No interval data for %s", target_date.isoformat())
            return []

        readings = body["response"].get("intervalDataResponse", [])
        LOGGER.debug("Got %d interval readings for %s", len(readings), target_date.isoformat())
        return readings
