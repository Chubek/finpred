"""One read-only Demand API v3.3 search of Booking.com's sandbox inventory."""

from contextlib import closing
from datetime import date, datetime, timezone
import http.client
import json
import re
import ssl

from .inputs import parse_json


HOST = "demandapi-sandbox.booking.com"
PATH = "/3.3/accommodations/search"
API_TOKEN = "CARAVANSARY_BOOKING_API_TOKEN"
AFFILIATE_ID = "CARAVANSARY_BOOKING_AFFILIATE_ID"
_SANDBOX_IDS = {12337, 42709, 2098153, 3427703, 4462291, 5476508, 10507360}
_MAX_BODY = 512 * 1024
_TIMEOUT = 10


def search_request(cell, *, today):
    """Project a validated plan row to the sandbox search request."""
    if cell["source"] != "booking" or cell["status"] != "pending":
        raise ValueError("the pilot needs a verified Booking sandbox property mapping")
    property_id = cell["provider_property_id"]
    if (not isinstance(property_id, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", property_id)
            or int(property_id) not in _SANDBOX_IDS):
        raise ValueError("the pilot needs a documented numeric Booking sandbox accommodation ID")
    request = cell["request_context"]
    checkin, checkout = (date.fromisoformat(request[field]) for field in ("checkin", "checkout"))
    if checkin < today or (checkout - today).days > 500 or not 1 <= (checkout - checkin).days <= 90:
        raise ValueError("Booking requires a stay of 1–90 nights within the next 500 days")
    guest = request["guest_configuration"]
    return {
        "accommodations": [int(property_id)],
        "booker": {"country": request["booker_country"].lower(), "platform": "desktop"},
        "checkin": request["checkin"],
        "checkout": request["checkout"],
        "currency": request["currency"],
        "guests": {
            "number_of_adults": guest["adults"],
            "number_of_rooms": guest["rooms"],
            "children": guest["child_ages"],
            "allocation": [
                {"number_of_adults": room["adults"], "children": room["child_ages"]}
                for room in guest["allocation"]
            ],
        },
        "extras": ["products", "extra_charges"],
    }


def _status_reason(status):
    if status == 401:
        return "authentication_failed"
    if status == 403:
        return "permission_denied"
    if status == 429:
        return "rate_limited"
    if 300 <= status < 400:
        return "redirect_blocked"
    return "http_error"


def _summarize(data, request):
    value = parse_json(data.decode("utf-8"))
    if (not isinstance(value, dict) or value.get("errors")
            or not isinstance(value.get("request_id"), str) or not value["request_id"]
            or not isinstance(value.get("data"), list)):
        raise ValueError("invalid response")
    metadata = value.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("invalid pagination metadata")
    next_page = metadata.get("next_page")
    if next_page is not None and (not isinstance(next_page, str) or not next_page):
        raise ValueError("invalid next page token")
    data = value["data"]
    if not data:
        return {"outcome": "no_match", "has_more": next_page is not None}
    if (len(data) != 1 or not isinstance(data[0], dict)
            or type(data[0].get("id")) is not int or data[0]["id"] != request["accommodations"][0]):
        raise ValueError("unexpected accommodation")
    item = data[0]
    products = item.get("products", [])
    if not isinstance(products, list) or not all(isinstance(value, dict) for value in products):
        raise ValueError("invalid products")
    currency, price = item.get("currency"), item.get("price")
    total = price.get("total") if isinstance(price, dict) else None
    amount = total.get("booker_currency") if isinstance(total, dict) else None
    return {
        "outcome": "matched",
        "has_more": next_page is not None,
        "products_reported": len(products),
        "total_in_requested_currency": (
            isinstance(currency, dict) and currency.get("booker") == request["currency"]
            and type(amount) in (float, int) and amount >= 0
        ),
    }


def _read_response(response, request, report):
    report["http_status"] = response.status
    if response.status != 200:
        return _status_reason(response.status)
    if (response.getheader("Content-Type", "").partition(";")[0].strip().lower() != "application/json"
            or response.getheader("Content-Encoding", "identity").lower() != "identity"):
        return "unexpected_content"
    length = response.length
    if length is not None and length > _MAX_BODY:
        return "response_too_large"
    data = response.read(_MAX_BODY + 1)
    if len(data) > _MAX_BODY:
        return "response_too_large"
    if length is not None and len(data) != length:
        return "invalid_response"
    try:
        report.update(_summarize(data, request))
    except ValueError:
        return "invalid_response"
    return None


def run_sandbox(cell, *, today, environ):
    """Send exactly one sandbox search; emit only a sanitized pilot summary.

    The caller must approve the request and supply only the authorized API
    credentials. This function does not read files, follow redirects, retry,
    fetch more pages, make reservations, or produce coverage observations.
    """
    request = search_request(cell, today=today)
    token = environ.get(API_TOKEN)
    affiliate = environ.get(AFFILIATE_ID)
    if (not isinstance(token, str) or len(token) > 4096 or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token)
            or not isinstance(affiliate, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", affiliate)):
        raise ValueError(f"configure {API_TOKEN} and {AFFILIATE_ID} with partner API credentials")
    body = json.dumps(request, separators=(",", ":")).encode("ascii")
    # Verified client context without the SSLKEYLOGFILE behavior of
    # create_default_context(), which could otherwise open a secrets log.
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls.load_default_certs()
    client = http.client.HTTPSConnection(HOST, timeout=_TIMEOUT, context=tls)
    report = {
        "kind": "caravansary.booking-sandbox-pilot@1",
        "attempts": 1,
        "started_at": _now(),
    }
    try:
        client.request("POST", PATH, body=body, headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Affiliate-Id": affiliate,
        })
        with closing(client.getresponse()) as response:
            reason = _read_response(response, request, report)
            if reason is not None:
                report.update(outcome="failed", reason=reason)
    except (OSError, http.client.HTTPException):
        report.update(outcome="failed", reason="transport_error")
    finally:
        client.close()
    report["finished_at"] = _now()
    return report


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
