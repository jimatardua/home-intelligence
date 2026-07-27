"""AWS Lambda bridge between the Alexa Smart Home Skill API and Home Assistant.

Alexa invokes this function directly (no API Gateway involved) for every
smart-home directive: discovery, and every power/volume/source/etc. command
for whichever entities `alexa: smart_home:` exposes in Home Assistant's own
`configuration.yaml`. The only job here is forwarding the directive to HA's
`/api/alexa/smart_home` endpoint with the caller's OAuth bearer token, and
relaying the response back unchanged -- all the actual Alexa protocol logic
(capability discovery, entity-to-interface mapping) lives in HA itself.

Deliberately stdlib-only (`urllib.request`, not `requests`): AWS Lambda's
Python runtime doesn't bundle `requests`, and pulling it in would mean
packaging a dependency zip instead of uploading this one file directly,
for a bridge simple enough that stdlib already covers it -- same
stdlib-only-in-production bias as `energy_report`/`home_dashboard`.

Required environment variable:
    BASE_URL -- Home Assistant's own internet-reachable URL, no trailing
        slash (e.g. "https://domus.ardua.com").

Optional:
    NOT_VERIFY_SSL -- if set (to anything), skip TLS certificate
        verification. For local testing against a self-signed cert only --
        never set this in the real deployed Lambda.
    DEBUG -- if set, log at DEBUG level (includes the outgoing directive and
        HA's raw response).
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.error
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if os.environ.get("DEBUG") else logging.INFO)

HA_API_PATH = "/api/alexa/smart_home"
REQUEST_TIMEOUT_SECONDS = 10


def _extract_token(event: dict) -> str | None:
    """Alexa puts the bearer token in different places by directive type.

    Discovery directives carry it at payload.scope.token; almost every other
    directive (power control, etc.) carries it at endpoint.scope.token
    instead. Both are checked since there's no single fixed location.
    """
    directive = event.get("directive", {})

    endpoint_scope = directive.get("endpoint", {}).get("scope", {})
    if endpoint_scope.get("token"):
        return endpoint_scope["token"]

    payload_scope = directive.get("payload", {}).get("scope", {})
    if payload_scope.get("token"):
        return payload_scope["token"]

    return None


def _error_response(event: dict, error_type: str, message: str) -> dict:
    directive = event.get("directive", {})
    header = directive.get("header", {})
    return {
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "ErrorResponse",
                "messageId": header.get("messageId", ""),
                "payloadVersion": "3",
            },
            "endpoint": directive.get("endpoint", {}),
            "payload": {
                "type": error_type,
                "message": message,
            },
        }
    }


def lambda_handler(event: dict, context) -> dict:
    logger.debug("Received directive: %s", json.dumps(event))

    base_url = os.environ.get("BASE_URL")
    if not base_url:
        logger.error("BASE_URL environment variable is not set")
        return _error_response(event, "INTERNAL_ERROR", "BASE_URL not configured")

    token = _extract_token(event)
    if not token:
        logger.error("No bearer token found in directive")
        return _error_response(
            event, "INVALID_AUTHORIZATION_CREDENTIAL", "Missing access token"
        )

    url = f"{base_url.rstrip('/')}{HA_API_PATH}"
    body = json.dumps(event).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )

    ssl_context = None
    if os.environ.get("NOT_VERIFY_SSL"):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl_context
        ) as response:
            response_body = response.read().decode("utf-8")
            logger.debug("HA response (%s): %s", response.status, response_body)
            return json.loads(response_body)
    except urllib.error.HTTPError as err:
        error_body = err.read().decode("utf-8", errors="replace")
        logger.error("HA returned HTTP %s: %s", err.code, error_body)
        if err.code in (401, 403):
            return _error_response(
                event, "INVALID_AUTHORIZATION_CREDENTIAL", "Home Assistant rejected the token"
            )
        return _error_response(event, "INTERNAL_ERROR", f"HA returned HTTP {err.code}")
    except urllib.error.URLError as err:
        logger.error("Could not reach Home Assistant at %s: %s", url, err.reason)
        return _error_response(event, "INTERNAL_ERROR", "Could not reach Home Assistant")
    except (json.JSONDecodeError, ValueError) as err:
        logger.error("Could not parse Home Assistant's response: %s", err)
        return _error_response(event, "INTERNAL_ERROR", "Invalid response from Home Assistant")
