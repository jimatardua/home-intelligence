#!/usr/bin/env python3
"""Standalone proof-of-concept: log into csapps.rockymountainpower.net and
call the encrypted account/usage API directly, bypassing the browser.

Run this yourself in a terminal so your password never passes through chat
or gets logged anywhere:

    python3 poc_encrypted_client.py

It prompts for your RMP username/password via getpass (not echoed to the
terminal). The password is held in memory only long enough for the single
login POST and is never printed or written to disk. Paste the full stdout
back — it does not print your password, account number, or session cookies.

Purpose: validate the reverse-engineered request-encryption scheme (RSA-4096
dual keypair handshake + AES-GCM + RSA-PKCS1v15 signing) against the live
API before writing it into the real Home Assistant integration.

Credentials: copy .env.example to .env and fill in RMP_USERNAME/RMP_PASSWORD
to skip the interactive prompts on repeat runs. .env is gitignored -- never
commit it. If .env is absent or a value is blank, this falls back to
prompting (password via getpass, never echoed).
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import re
import secrets
import sys
from datetime import date, timedelta

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

BASE_URL = "https://csapps.rockymountainpower.net"
LOGIN_URL = f"{BASE_URL}/oauth2/authorization/B2C_1A_PAC_SIGNIN"
B2C_TENANT = "bheb2c.onmicrosoft.com"
B2C_POLICY = "B2C_1A_PAC_signin"
B2C_LOGIN_HOST = "login.csapps.rockymountainpower.net"
B2C_POLICY_BASE = f"https://{B2C_LOGIN_HOST}/{B2C_TENANT}/{B2C_POLICY}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

SETTINGS_RE = re.compile(r"var SETTINGS = (\{.*?\});", re.DOTALL)
BUNDLE_SIG_RE = re.compile(r"main\.[0-9a-f]+\.js")


def log(msg: str) -> None:
    print(f"[poc] {msg}", file=sys.stderr)


def parse_settings(html: str) -> dict:
    m = SETTINGS_RE.search(html)
    if not m:
        raise RuntimeError("Could not find SETTINGS blob in login page HTML")
    return json.loads(m.group(1))


def raise_with_body(r: requests.Response, step: str) -> None:
    if not r.ok:
        raise RuntimeError(f"{step} failed: HTTP {r.status_code}\n{r.text[:1000]}")


def xsrf_headers(session: requests.Session) -> dict:
    # Angular's HttpClientXsrfModule (default cookie/header names, confirmed
    # in the JS bundle) auto-attaches this on every mutating same-origin
    # request. requests.Session doesn't do this automatically.
    token = session.cookies.get("XSRF-TOKEN", domain="csapps.rockymountainpower.net")
    if token is None:
        token = session.cookies.get("XSRF-TOKEN")
    if token is None:
        log("WARNING: no XSRF-TOKEN cookie found yet; request may be rejected")
        return {}
    return {"X-XSRF-TOKEN": token}


def login(session: requests.Session, username: str, password: str) -> None:
    log("GET login start page")
    r = session.get(LOGIN_URL, headers={"User-Agent": USER_AGENT})
    raise_with_body(r, "GET login start page")

    settings = parse_settings(r.text)
    csrf = settings["csrf"]
    trans_id = settings["transId"]
    sig_match = BUNDLE_SIG_RE.search(r.text)
    log(f"parsed SETTINGS ok; site_bundle_signature={sig_match.group(0) if sig_match else 'not found'}")

    log("POST SelfAsserted")
    cookie_dump = [(c.name, c.domain) for c in session.cookies]
    log(f"cookies before SelfAsserted: {cookie_dump}")
    prepared_cookie_header = session.cookies.get_dict(domain="login.csapps.rockymountainpower.net")
    log(f"cookie header would-be length for login host: {sum(len(k)+len(v)+3 for k,v in prepared_cookie_header.items())} bytes")
    r = session.post(
        f"{B2C_POLICY_BASE}/SelfAsserted",
        params={"tx": trans_id, "p": B2C_POLICY},
        headers={"X-CSRF-TOKEN": csrf, "User-Agent": USER_AGENT},
        data={
            "request_type": "RESPONSE",
            "signInName": username,
            "password": password,
        },
    )
    log(f"SelfAsserted actual request headers sent: {dict(r.request.headers)}")
    log(f"SelfAsserted actual request URL sent: {r.request.url}")
    raise_with_body(r, "POST SelfAsserted")
    try:
        body = r.json()
        status = body.get("status")
        if status is not None and str(status) != "200":
            raise RuntimeError(f"SelfAsserted rejected credentials: {body}")
    except ValueError:
        pass  # non-JSON body is fine; the final redirect check below is authoritative

    log("GET confirmed (follows the oauth2/code redirect chain)")
    r = session.get(
        f"{B2C_POLICY_BASE}/api/CombinedSigninAndSignup/confirmed",
        params={"rememberMe": "false", "csrf_token": csrf, "tx": trans_id, "p": B2C_POLICY},
        headers={"User-Agent": USER_AGENT},
    )
    raise_with_body(r, "GET confirmed")
    if "oauth2/code" not in r.url:
        raise RuntimeError(f"Did not land on the oauth2/code callback; final URL host/path: {r.url.split('?')[0]}")
    log("login flow complete, session cookie established")


def do_handshake(session: requests.Session):
    log("generating RSA-4096 signing keypair (a few seconds)...")
    sign_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    log("generating RSA-4096 encryption keypair (a few seconds)...")
    enc_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    sign_pub_spki = sign_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    enc_pub_spki = enc_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    body = base64.b64encode(sign_pub_spki).decode() + ":" + base64.b64encode(enc_pub_spki).decode()

    log("POST /idm/handshake")
    headers = {
        "Content-Type": "application/octet-stream",
        "X-WCSSS-Policy": "0",
        "User-Agent": USER_AGENT,
    }
    headers.update(xsrf_headers(session))
    r = session.post(f"{BASE_URL}/idm/handshake", data=body, headers=headers)
    raise_with_body(r, "POST /idm/handshake")

    raw_text = r.text.strip()
    log(f"handshake response: {len(raw_text)} chars, content-type={r.headers.get('Content-Type')!r}")
    log(f"handshake response repr (first 300 chars): {raw_text[:300]!r}")

    # RSA-4096 OAEP ciphertext must decode to exactly 512 bytes. If the raw
    # response isn't a single base64 blob of that shape, dump enough to
    # diagnose the actual format instead of failing inside decrypt().
    candidate = raw_text
    if ":" in raw_text:
        parts = raw_text.split(":")
        log(f"response contains {len(parts)} colon-separated part(s), lengths: {[len(p) for p in parts]}")
        candidate = parts[-1]

    try:
        decoded = base64.b64decode(candidate)
    except Exception as exc:
        raise RuntimeError(f"handshake response is not valid base64: {exc}\nraw: {raw_text[:300]!r}")
    log(f"base64-decoded handshake payload length = {len(decoded)} bytes (need 512 for RSA-4096 OAEP)")

    if len(decoded) != 512:
        raise RuntimeError(
            f"handshake payload is {len(decoded)} bytes, not the 512 bytes an RSA-4096 OAEP "
            f"ciphertext requires -- format assumption is wrong. Full raw response:\n{raw_text}"
        )

    aes_key_bytes = enc_key.decrypt(
        decoded,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    log(f"handshake ok; decrypted AES key length = {len(aes_key_bytes)} bytes")
    return sign_key, aes_key_bytes


def encrypt_body(sign_key, aes_key_bytes: bytes, payload: dict) -> tuple[str, dict]:
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = sign_key.sign(plaintext, padding.PKCS1v15(), hashes.SHA256())
    iv = secrets.token_bytes(12)
    ciphertext = AESGCM(aes_key_bytes).encrypt(iv, plaintext, None)
    body_str = base64.b64encode(iv).decode() + base64.b64encode(ciphertext).decode()
    headers = {
        "Content-Type": "application/json",
        "X-WCSSS-Content-Signature": base64.b64encode(signature).decode(),
    }
    return body_str, headers


def secure_post(session: requests.Session, sign_key, aes_key_bytes: bytes, path: str, payload: dict) -> dict:
    body_str, headers = encrypt_body(sign_key, aes_key_bytes, payload)
    headers["User-Agent"] = USER_AGENT
    headers.update(xsrf_headers(session))
    r = session.post(f"{BASE_URL}{path}", data=body_str, headers=headers)
    log(f"POST {path} -> HTTP {r.status_code}")
    raise_with_body(r, f"POST {path}")
    return r.json()


def main() -> None:
    load_dotenv()  # loads .env from cwd if present; no-op otherwise

    username = os.environ.get("RMP_USERNAME", "").strip()
    if not username:
        username = input("RMP username: ").strip()
    else:
        log("using RMP_USERNAME from .env")

    password = os.environ.get("RMP_PASSWORD", "")
    if not password:
        password = getpass.getpass("RMP password (hidden): ")
    else:
        log("using RMP_PASSWORD from .env")

    session = requests.Session()
    login(session, username, password)
    log(f"cookies present after login (names only): {sorted(c.name for c in session.cookies)}")
    sign_key, aes_key_bytes = do_handshake(session)

    log("calling getAccountList")
    account_list_resp = secure_post(
        session,
        sign_key,
        aes_key_bytes,
        "/api/self-service/getAccountList",
        {
            "getAccountListRequestBody": {
                "request": {"webUserID": username},
                "domain": {"pacifiCorpSubsidiary": "RockyMountainPower"},
            }
        },
    )
    accounts = account_list_resp["getAccountListResponseBody"]["accountList"]["webAccount"]
    account = accounts[0]
    customer_idn = account["customer"]["idn"]
    account_sequence = account["sequence"]
    log("getAccountList ok; resolved customerIDN/accountSequence (values withheld from log)")

    log("calling getMeteredAgreements")
    agreements_resp = secure_post(
        session,
        sign_key,
        aes_key_bytes,
        "/api/account/getMeteredAgreements",
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
    agreement = agreements_resp["getMeteredAgreementsResponseBody"]["meteredAgreementList"]["meteredAgreement"][0]
    log("getMeteredAgreements ok; resolved siteIDN/serviceSequence/agreementSequence")

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    log(f"calling getIntervalUsageForDate for {yesterday} (registerType guess: '01' -- unconfirmed, watch for an error here)")
    usage_resp = secure_post(
        session,
        sign_key,
        aes_key_bytes,
        "/api/energy-usage/getIntervalUsageForDate",
        {
            "getIntervalUsageForDateRequestBody": {
                "request": {
                    "siteIDN": agreement["siteIDN"],
                    "registerType": "01",
                    "serviceSequence": agreement["serviceSequence"],
                    "readDate": yesterday,
                    "agreement": {
                        "customerIDN": agreement["customerIDN"],
                        "accountSequence": agreement["accountSequence"],
                        "agreementSequence": agreement["agreementSequence"],
                    },
                }
            }
        },
    )
    print("\n=== getIntervalUsageForDate response ===")
    print(json.dumps(usage_resp, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - top-level diagnostic script
        log(f"FAILED: {exc}")
        sys.exit(1)
