from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tier_plugin", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="studenttier",
            name="exam",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="studenttier",
            name="subject_scores",
            field=models.JSONField(default=dict),
        ),
    ]
