from django.db import migrations


def create_users_for_officials(apps, schema_editor):
    """Give every ward official a Django user account.

    The stored password is already a Django hash, so it is copied across
    verbatim rather than reset. Officials keep signing in with the password
    they already use, and no plain-text password ever has to exist for this
    migration to run.
    """

    WardOfficial = apps.get_model("complaint", "WardOfficial")
    User = apps.get_model("auth", "User")

    for official in WardOfficial.objects.all():

        if official.user_id:
            continue

        user = User.objects.filter(username=official.username).first()

        if user is None:

            user = User.objects.create(
                username=official.username,
                password=official.password,
                first_name=(official.full_name or "")[:150],
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )

        official.user = user
        official.save(update_fields=["user"])


def unlink_users(apps, schema_editor):
    """Detach the accounts, leaving the original password column untouched."""

    WardOfficial = apps.get_model("complaint", "WardOfficial")

    WardOfficial.objects.update(user=None)


class Migration(migrations.Migration):

    dependencies = [
        ("complaint", "0011_wardofficial_user"),
        ("auth", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_users_for_officials, unlink_users),
    ]
