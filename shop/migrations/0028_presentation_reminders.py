from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('shop', '0027_skyroom_rooms'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.CreateModel(
        name='PresentationReminder',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('batch_id', models.UUIDField(db_index=True)),
            ('recipient', models.EmailField(max_length=254)),
            ('status', models.CharField(choices=[('PENDING', 'Pending'), ('SENT', 'Sent'), ('FAILED', 'Failed')], default='PENDING', max_length=10)),
            ('attempts', models.PositiveSmallIntegerField(default=0)),
            ('available_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('sent_at', models.DateTimeField(blank=True, null=True)),
            ('last_error', models.CharField(blank=True, max_length=100)),
            ('presentation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reminder_emails', to='shop.presentation')),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='presentation_reminders', to=settings.AUTH_USER_MODEL)),
            ('queued_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='queued_presentation_reminders', to=settings.AUTH_USER_MODEL)),
        ],
        options={
            'permissions': [('send_presentation_reminders', 'Can send reminder emails to presentation participants')],
            'constraints': [models.UniqueConstraint(fields=('batch_id', 'user'), name='unique_reminder_batch_user')],
        },
    )]
