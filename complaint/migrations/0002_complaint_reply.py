from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("complaint", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="complaint",
            name="reply",
            field=models.TextField(
                blank=True,
                null=True
            ),
        ),
    ]