from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('shop', '0028_presentation_reminders')]

    operations = [migrations.AddField(
        model_name='presentation',
        name='allow_registration_after_start',
        field=models.BooleanField(
            default=False,
            help_text='Allow registration and checkout after the scheduled start. Registration must still be open and capacity available. Close registration manually when finished.',
        ),
    )]
