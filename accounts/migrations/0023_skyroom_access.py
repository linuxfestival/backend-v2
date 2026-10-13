from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('accounts', '0022_resume_submission')]
    operations = [
        migrations.CreateModel(name='SkyroomCredential', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('username', models.CharField(max_length=255, unique=True)),
            ('encrypted_password', models.TextField(editable=False)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='skyroom_credential', to=settings.AUTH_USER_MODEL)),
        ], options={'permissions': [
            ('export_skyroom_credentials', 'Can export Skyroom usernames and passwords'),
            ('email_skyroom_credentials', 'Can email Skyroom credentials to participants'),
        ]}),
        migrations.CreateModel(name='SkyroomEmail', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('recipient', models.EmailField(max_length=254)),
            ('presentations', models.JSONField(default=list)),
            ('status', models.CharField(choices=[('PENDING', 'Pending'), ('SENT', 'Sent'), ('FAILED', 'Failed')], default='PENDING', max_length=10)),
            ('attempts', models.PositiveSmallIntegerField(default=0)),
            ('available_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('sent_at', models.DateTimeField(blank=True, null=True)),
            ('last_error', models.CharField(blank=True, max_length=100)),
            ('credential', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='emails', to='accounts.skyroomcredential')),
        ]),
    ]
