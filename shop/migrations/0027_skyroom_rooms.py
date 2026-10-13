from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('shop', '0026_coupon_redemption')]
    operations = [
        migrations.AddField(model_name='presentation', name='is_skyroom', field=models.BooleanField(default=False, help_text='Enable Skyroom access for completed participants.')),
        migrations.AddField(model_name='presentation', name='skyroom_room_url', field=models.URLField(blank=True, help_text='Room link shown to registered users and included in credential emails/exports.')),
    ]
