import re

from django.db import migrations


def normalize(raw):
    """Standalone copy of complaint.sms.normalize_phone.

    Migrations must not import application code, which is free to change after
    this migration has been written.
    """

    if not raw:
        return None

    digits = re.sub(r"\D", "", str(raw))

    if digits.startswith("977") and len(digits) > 10:
        digits = digits[3:]

    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or not digits.startswith(("97", "98")):
        return None

    return digits


def normalize_existing_phones(apps, schema_editor):
    """Rewrite phone numbers stored before the form normalised them.

    Complaints filed early hold values like "981 4198452". Citizen login looks
    up complaints by exact phone, so without this a citizen could sign in and
    see none of their own complaints.

    Numbers that are not valid Nepali mobiles are left untouched rather than
    guessed at.
    """

    Complaint = apps.get_model("complaint", "Complaint")

    for complaint in Complaint.objects.all():

        cleaned = normalize(complaint.phone)

        if cleaned and cleaned != complaint.phone:
            complaint.phone = cleaned
            complaint.save(update_fields=["phone"])


def noop_reverse(apps, schema_editor):
    """The original spacing is not worth restoring."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("complaint", "0009_citizen_otpcode_alter_smslog_purpose_upvote_citizen_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_existing_phones, noop_reverse),
    ]
