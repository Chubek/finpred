#!/usr/bin/env python3
"""Exercise the sandbox command with synthetic responses and no network."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import ssl
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plugins.caravansary import caravansary
from plugins.caravansary.caravansary_core import booking_pilot


EXAMPLE = ROOT / "plugins/caravansary/examples/booking-sandbox/pilot.crs"
TODAY = date(2026, 11, 26)
CLOCK = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
TOKEN = "fictional-partner-token-only"
CREDS = {booking_pilot.API_TOKEN: TOKEN, booking_pilot.AFFILIATE_ID: "98765"}


def reply(status=200, *, media="application/json", encoding="identity", body=None, length=None):
    headers = {"Content-Type": media, "Content-Encoding": encoding}
    response = Mock(status=status, length=length)
    response.getheader.side_effect = headers.get
    response.read.return_value = body if body is not None else json.dumps({
        "request_id": "not-retained",
        "data": [{
            "id": 10507360,
            "currency": {"booker": "EUR"},
            "price": {"total": {"booker_currency": 123.75}},
            "products": [{"id": "not-retained"}],
            "url": "https://booking.example/do-not-retain",
        }],
        "metadata": {"next_page": "do-not-follow"},
    }).encode()
    return response


class BookingPilotTest(unittest.TestCase):
    def setUp(self):
        self.cell, = caravansary.plan(EXAMPLE, TODAY)
        self.connection = Mock()
        self.factory = self.enter_patch(patch.object(
            booking_pilot.http.client, "HTTPSConnection", return_value=self.connection,
        ))

    def enter_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def command(self, *args, environ=None, script=EXAMPLE):
        out, err = StringIO(), StringIO()
        with patch.dict(os.environ, environ or {}, clear=True), \
                patch.object(caravansary, "_utc", return_value=CLOCK), \
                redirect_stdout(out), redirect_stderr(err):
            status = caravansary.main(["pilot-booking", str(script), *args])
        return status, out.getvalue(), err.getvalue()

    def test_command_makes_one_verified_tls_post_and_redacts_response(self):
        response = self.connection.getresponse.return_value = reply()
        status, out, err = self.command("--confirm-authorized", environ=CREDS)
        self.assertEqual((status, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["outcome"], "matched")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["products_reported"], 1)
        self.assertTrue(result["has_more"])
        self.assertTrue(result["total_in_requested_currency"])
        for raw in (TOKEN, '"98765"', "123.75", "not-retained", "do-not-follow"):
            self.assertNotIn(raw, out)
        self.factory.assert_called_once()
        self.assertEqual(self.factory.call_args.args, ("demandapi-sandbox.booking.com",))
        tls = self.factory.call_args.kwargs["context"]
        self.assertEqual(tls.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(tls.check_hostname)
        self.assertIsNone(tls.keylog_filename)
        self.connection.request.assert_called_once()
        self.assertEqual(self.connection.request.call_args.args,
                         ("POST", "/3.3/accommodations/search"))
        options = self.connection.request.call_args.kwargs
        self.assertEqual(options["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(options["headers"]["X-Affiliate-Id"], "98765")
        self.assertEqual(json.loads(options["body"]), {
            "accommodations": [10507360],
            "booker": {"country": "nl", "platform": "desktop"},
            "checkin": "2026-11-26",
            "checkout": "2026-11-27",
            "currency": "EUR",
            "guests": {
                "number_of_adults": 2, "number_of_rooms": 1, "children": [],
                "allocation": [{"number_of_adults": 2, "children": []}],
            },
            "extras": ["products", "extra_charges"],
        })
        response.close.assert_called_once()
        self.connection.close.assert_called_once()

    def test_preflight_blocks_without_authority_credentials_or_one_cell(self):
        status, out, err = self.command(environ=CREDS)
        self.assertEqual((status, out), (1, ""))
        self.assertIn("--confirm-authorized", err)
        for environ in ({"BOOKING_USERNAME": "fixture", "BOOKING_PASSWORD": TOKEN},
                        CREDS | {booking_pilot.API_TOKEN: TOKEN + "\r\nExtra: header"}):
            status, out, err = self.command("--confirm-authorized", environ=environ)
            self.assertEqual((status, out), (1, ""))
            self.assertIn(booking_pilot.API_TOKEN, err)
            self.assertNotIn(TOKEN, err)
        status, out, err = self.command(
            "--confirm-authorized", environ=CREDS,
            script=ROOT / "docs/caravansary/examples/riviera.crs",
        )
        self.assertEqual((status, out), (1, ""))
        self.assertIn("exactly one matrix cell", err)
        status, out, err = self.command("--confirm-authorized", "--date", "2026-11-25", environ=CREDS)
        self.assertEqual((status, out), (1, ""))
        self.assertIn("next 500 days", err)
        for invalid in (self.cell | {"provider_property_id": "10004"},
                        self.cell | {"status": "unsupported"}):
            with self.assertRaises(ValueError):
                booking_pilot.run_sandbox(invalid, today=TODAY, environ=CREDS)
        self.factory.assert_not_called()

    def test_http_errors_do_not_read_body_retry_or_redirect(self):
        for status, reason in ((302, "redirect_blocked"), (401, "authentication_failed"),
                               (403, "permission_denied"), (429, "rate_limited"), (500, "http_error")):
            with self.subTest(status=status):
                self.connection.reset_mock()
                response = self.connection.getresponse.return_value = reply(status=status)
                code, out, err = self.command("--confirm-authorized", environ=CREDS)
                self.assertEqual((code, err), (1, ""))
                self.assertEqual(json.loads(out)["reason"], reason)
                response.read.assert_not_called()
                response.close.assert_called_once()
                self.connection.request.assert_called_once()
                self.connection.close.assert_called_once()

    def test_no_match_malformed_and_overlarge_responses(self):
        for response, outcome in (
            (reply(body=b'{"request_id":"offline","data":[]}'), "no_match"),
            (reply(body=b'{"request_id":"offline","data":[{"id":12337}]}'), "invalid_response"),
            (reply(body=b'{"request_id":"offline","data":[],"data":[]}'), "invalid_response"),
            (reply(body=b'{"request_id":"offline","data":[]}', length=99), "invalid_response"),
            (reply(body=b"x" * (512 * 1024 + 1)), "response_too_large"),
            (reply(length=512 * 1024 + 1), "response_too_large"),
            (reply(media="text/html"), "unexpected_content"),
            (reply(encoding="gzip"), "unexpected_content"),
        ):
            self.connection.getresponse.return_value = response
            result = booking_pilot.run_sandbox(self.cell, today=TODAY, environ=CREDS)
            self.assertEqual(result.get("reason", result["outcome"]), outcome)
            self.assertNotIn("availability", result)
        self.connection.request.side_effect = TimeoutError("fixture error not retained")
        result = booking_pilot.run_sandbox(self.cell, today=TODAY, environ=CREDS)
        self.assertEqual(result["reason"], "transport_error")
        self.assertNotIn("fixture error", repr(result))


if __name__ == "__main__":
    unittest.main()
