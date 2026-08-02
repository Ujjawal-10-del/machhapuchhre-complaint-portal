import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Retire WardOfficial's own username and password columns.

    Every row was given a linked auth user in 0012, so the link can be made
    required and the duplicated credentials dropped. Authentication now runs
    entirely through django.contrib.auth.
    """

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("complaint", "0012_wardofficials_to_auth_users"),
    ]

    operations = [

        migrations.AlterField(
            model_name="wardofficial",
            name="user",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ward_official",
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        migrations.RemoveField(
            model_name="wardofficial",
            name="username",
        ),

        migrations.RemoveField(
            model_name="wardofficial",
            name="password",
        ),

    ]
