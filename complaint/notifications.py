"""What the portal says to citizens over SMS.

Kept apart from :mod:`complaint.sms`, which only knows how to deliver text.

Every message here is deliberately short. Devanagari forces a 70-character SMS
segment instead of 160, so wording that looks harmless can double the bill for
the municipality. Details belong on the tracking page, not in the message.
"""

from django.conf import settings

from .sms import send_sms


# Status values are stored in English for the ward interface; citizens get Nepali.
STATUS_LABELS_NE = {
    "Pending": "पेन्डिङ",
    "In Progress": "प्रक्रियामा",
    "Resolved": "समाधान भयो",
}


def status_label(status):
    return STATUS_LABELS_NE.get(status, status)


def build_registration_message(complaint):
    # Kept under 70 characters so this stays a single Unicode SMS segment.
    return (
        "गुनासो दर्ता भयो। ID: %s । यो नम्बर सुरक्षित राख्नुहोस्।"
        % complaint.complaint_id
    )


def build_status_message(complaint):

    # On resolution the citizen is asked to confirm, because the ranking should
    # not reward an office for merely claiming the work is done. No link: a URL
    # would push this past 70 characters and into a second billed segment.
    if complaint.status == "Resolved":
        return (
            "गुनासो %s समाधान भयो। कृपया ट्र्याक पेजमा पुष्टि गर्नुहोस्।"
            % complaint.complaint_id
        )

    return (
        "गुनासो %s को अवस्था: %s ।"
        % (complaint.complaint_id, status_label(complaint.status))
    )


def build_otp_message(code, minutes):
    # Under 70 characters, so a login code is never billed as two segments.
    return (
        "गुनासो पोर्टल कोड: %s । %d मिनेटसम्म मान्य।"
        % (code, minutes)
    )


def notify_login_code(phone, code, minutes):
    """Text a one-time login code to a citizen.

    With DEBUG on, the code is kept in the SMS log so it can be read from the
    Django admin while no real gateway is connected. With DEBUG off it is
    redacted, because a live login code sitting in the database would let
    anyone with admin or database access sign in as any citizen.
    """

    message = build_otp_message(code, minutes)

    recorded = message if settings.DEBUG else build_otp_message("******", minutes)

    return send_sms(
        phone,
        message,
        purpose="login_code",
        log_message=recorded,
    )


def notify_registered(complaint):
    """Send the tracking ID.

    Without this the ID exists only on the success page; a citizen who closes
    that tab has no way to look their complaint up again.
    """

    return send_sms(
        complaint.phone,
        build_registration_message(complaint),
        purpose="registration",
        complaint=complaint,
    )


def notify_status_change(complaint):
    """Tell the citizen their complaint moved to a new status."""

    return send_sms(
        complaint.phone,
        build_status_message(complaint),
        purpose="status_change",
        complaint=complaint,
    )
