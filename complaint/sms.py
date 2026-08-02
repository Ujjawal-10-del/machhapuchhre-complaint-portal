"""Provider-agnostic SMS delivery.

The portal only ever calls :func:`send_sms`. Which gateway actually carries the
message is decided by the ``SMS_BACKEND`` setting, so switching from the console
backend to a real Nepali gateway is a settings change, not a code change.

Only the standard library is used for HTTP so that deploying this needs no
extra packages beyond Django and Pillow.
"""

import json
import logging
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils.module_loading import import_string


logger = logging.getLogger(__name__)


class SMSError(Exception):
    """Raised by a backend when the gateway refuses or fails to accept a message."""


# ==================================================
# PHONE NUMBERS
# ==================================================

def normalize_phone(raw):
    """Return a Nepali mobile number as 10 digits, or None if it isn't one.

    Accepts the shapes people actually type: spaces, dashes, a +977 or 977
    country prefix, a leading zero. Nepali mobile numbers are 10 digits and
    begin 97 or 98; anything else is rejected rather than sent into the void,
    because a failed send still costs money.
    """

    if not raw:
        return None

    digits = re.sub(r"\D", "", str(raw))

    # Strip the country code, however it was written.
    if digits.startswith("977") and len(digits) > 10:
        digits = digits[3:]

    # Some people write the number with a leading zero.
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10:
        return None

    if not digits.startswith(("97", "98")):
        return None

    return digits


def is_valid_phone(raw):
    return normalize_phone(raw) is not None


# ==================================================
# MESSAGE COST
# ==================================================

# A GSM-7 segment holds 160 characters, but any Devanagari forces the whole
# message into UCS-2, where a segment is only 70. Nepali messages therefore
# cost several times more than they look like they should.
GSM7_SEGMENT = 160
UNICODE_SEGMENT = 70


def is_unicode_message(message):
    """True when the text cannot be sent in the cheap 7-bit alphabet."""

    return any(ord(char) > 127 for char in message)


def count_segments(message):
    """How many SMS segments this text will be billed as."""

    if not message:
        return 0

    size = UNICODE_SEGMENT if is_unicode_message(message) else GSM7_SEGMENT

    # Concatenated messages give up some payload to the joining header.
    if len(message) <= size:
        return 1

    size = 67 if is_unicode_message(message) else 153

    return -(-len(message) // size)


# ==================================================
# BACKENDS
# ==================================================

class BaseSMSBackend:
    """Interface every gateway adapter implements."""

    def send(self, phone, message):
        """Deliver the message. Return a short provider response string.

        Must raise :class:`SMSError` if the gateway did not accept it.
        """

        raise NotImplementedError


def _write_console(text):
    """Print text that may contain Devanagari without blowing up.

    The default Windows console is cp1252 and raises UnicodeEncodeError on
    Nepali. Writing UTF-8 bytes straight to the underlying buffer sidesteps the
    console codec; the replace-fallback covers anything still unwritable.
    """

    stream = sys.stdout

    buffer = getattr(stream, "buffer", None)

    if buffer is not None:

        try:
            buffer.write((text + "\n").encode("utf-8"))
            buffer.flush()
            return
        except Exception:
            pass

    encoding = getattr(stream, "encoding", None) or "utf-8"

    stream.write(
        (text + "\n").encode(encoding, errors="replace").decode(encoding)
    )


class ConsoleSMSBackend(BaseSMSBackend):
    """Prints instead of sending. The default, so development costs nothing."""

    def send(self, phone, message):

        segments = count_segments(message)

        _write_console(
            "\n" + "=" * 56
            + "\nSMS (console backend - not actually sent)"
            + "\n" + "=" * 56
            + "\nTo      : +977-%s" % phone
            + "\nSegments: %d (%s, %d chars)" % (
                segments,
                "unicode" if is_unicode_message(message) else "gsm-7",
                len(message),
            )
            + "\n" + "-" * 56
            + "\n" + message
            + "\n" + "=" * 56 + "\n"
        )

        return "console: printed, %d segment(s)" % segments


class HTTPSMSBackend(BaseSMSBackend):
    """Shared plumbing for gateways driven by a simple HTTP form POST."""

    endpoint = ""

    def build_payload(self, phone, message):
        raise NotImplementedError

    def send(self, phone, message):

        payload = urllib.parse.urlencode(
            self.build_payload(phone, message)
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        timeout = getattr(settings, "SMS_TIMEOUT", 10)

        try:

            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")

        except urllib.error.HTTPError as exc:

            detail = exc.read().decode("utf-8", errors="replace")

            raise SMSError("HTTP %s: %s" % (exc.code, detail[:300])) from exc

        except Exception as exc:

            raise SMSError("%s: %s" % (type(exc).__name__, exc)) from exc

        return self.interpret(body)

    def interpret(self, body):
        """Turn the raw response into a short string, raising on failure."""

        return body[:300]


class SparrowSMSBackend(HTTPSMSBackend):
    """Sparrow SMS (sparrowsms.com).

    Verify the parameter names against their current documentation before
    going live; gateways change these without much warning.
    """

    endpoint = "https://api.sparrowsms.com/v2/sms/"

    def build_payload(self, phone, message):

        token = getattr(settings, "SPARROW_SMS_TOKEN", "")
        sender = getattr(settings, "SPARROW_SMS_FROM", "")

        if not token:
            raise SMSError("SPARROW_SMS_TOKEN is not configured")

        return {
            "token": token,
            "from": sender,
            "to": phone,
            "text": message,
        }

    def interpret(self, body):

        try:
            data = json.loads(body)
        except ValueError:
            raise SMSError("unreadable response: %s" % body[:300])

        # Sparrow reports trouble via a response_code / message pair.
        code = data.get("response_code")

        if code not in (None, 200):
            raise SMSError("code %s: %s" % (code, data.get("response", data)))

        return "sparrow: %s" % json.dumps(data)[:280]


class AakashSMSBackend(HTTPSMSBackend):
    """Aakash SMS (aakashsms.com). Same caveat about verifying parameters."""

    endpoint = "https://sms.aakashsms.com/sms/v3/send/"

    def build_payload(self, phone, message):

        token = getattr(settings, "AAKASH_SMS_TOKEN", "")

        if not token:
            raise SMSError("AAKASH_SMS_TOKEN is not configured")

        return {
            "auth_token": token,
            "to": phone,
            "text": message,
        }

    def interpret(self, body):

        try:
            data = json.loads(body)
        except ValueError:
            raise SMSError("unreadable response: %s" % body[:300])

        if data.get("error"):
            raise SMSError(str(data)[:300])

        return "aakash: %s" % json.dumps(data)[:280]


def get_backend():
    """Instantiate the backend named by the SMS_BACKEND setting."""

    path = getattr(
        settings,
        "SMS_BACKEND",
        "complaint.sms.ConsoleSMSBackend"
    )

    return import_string(path)()


# ==================================================
# PUBLIC ENTRY POINT
# ==================================================

def send_sms(phone, message, purpose="", complaint=None, log_message=None):
    """Send one SMS and record the attempt. Never raises.

    A gateway outage must not stop a ward officer from updating a complaint, so
    every failure is caught, written to the log table and returned as a failed
    :class:`~complaint.models.SMSLog` row.

    ``log_message`` records something other than what was sent. Used for login
    codes, which are redacted in the log outside development so that reading
    the database does not hand over live codes.
    """

    from .models import SMSLog

    recorded = log_message if log_message is not None else message

    normalized = normalize_phone(phone)

    if not normalized:

        logger.warning("SMS skipped, unusable number %r", phone)

        return SMSLog.objects.create(
            complaint=complaint,
            phone=(phone or "")[:20],
            message=recorded,
            purpose=purpose,
            success=False,
            provider_response="skipped: not a valid Nepali mobile number",
        )

    if not getattr(settings, "SMS_ENABLED", True):

        return SMSLog.objects.create(
            complaint=complaint,
            phone=normalized,
            message=recorded,
            purpose=purpose,
            success=False,
            provider_response="skipped: SMS_ENABLED is False",
        )

    try:

        response = get_backend().send(normalized, message)
        success = True

    except SMSError as exc:

        logger.error("SMS to %s failed: %s", normalized, exc)

        response = str(exc)
        success = False

    except Exception as exc:

        # A backend bug must not take the request down with it.
        logger.exception("Unexpected SMS failure for %s", normalized)

        response = "%s: %s" % (type(exc).__name__, exc)
        success = False

    return SMSLog.objects.create(
        complaint=complaint,
        phone=normalized,
        message=recorded,
        purpose=purpose,
        success=success,
        provider_response=str(response)[:500],
    )
