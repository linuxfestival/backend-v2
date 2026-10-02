from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0019_user_is_signed_up_for_competition"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_first_login",
            field=models.BooleanField(
                default=True,
                help_text="Tracks whether the user needs to complete the post-registration onboarding flow.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="heard_about_us",
            field=models.CharField(
                blank=True,
                choices=[
                    ("telegram", "Telegram"),
                    ("instagram", "Instagram"),
                    ("linkedin", "LinkedIn"),
                    ("friends", "Friends / Word of Mouth"),
                    ("university", "University / Posters"),
                    ("hamkaran", "Hamkaran System"),
                    ("website", "LinuxFest Website / Search Engine"),
                    ("other", "Other"),
                ],
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="university",
            field=models.CharField(
                blank=True,
                max_length=150,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="hamkaran_announcement_consent",
            field=models.BooleanField(
                default=False,
            ),
        ),
    ]