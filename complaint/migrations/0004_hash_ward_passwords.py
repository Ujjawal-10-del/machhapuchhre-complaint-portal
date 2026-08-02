from django.contrib.auth.hashers import identify_hasher, make_password
from django.db import migrations


def hash_existing_passwords(apps, schema_editor):
    """Convert any plain-text ward password already in the table to a hash.

    Historical rows stored the password verbatim. Login now compares hashes, so
    those rows would stop authenticating unless they are upgraded here.
    """

    WardOfficial = apps.get_model("complaint", "WardOfficial")

    for official in WardOfficial.objects.all():

        if not official.password:
            continue

        try:
            identify_hasher(official.password)
        except ValueError:
            official.password = make_password(official.password)
            official.save(update_fields=["password"])


def noop_reverse(apps, schema_editor):
    """Hashing is one-way; the original passwords cannot be restored."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("complaint", "0003_alter_complaint_options_alter_complaint_ward"),
    ]

    operations = [
        migrations.RunPython(hash_existing_passwords, noop_reverse),
    ]
