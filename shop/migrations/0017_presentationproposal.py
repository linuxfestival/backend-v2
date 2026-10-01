import django.core.validators
from django.db import migrations, models
import shop.models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0016_payment_is_competition_payment'),
    ]

    operations = [
        migrations.CreateModel(
            name='PresentationProposal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(max_length=255)),
                ('biography', models.TextField()),
                ('organization', models.CharField(blank=True, max_length=255)),
                ('phone_number', models.CharField(max_length=32)),
                ('topic', models.CharField(max_length=255)),
                ('abstract', models.TextField()),
                ('slides', models.FileField(
                    upload_to='presentation_proposals/',
                    validators=[
                        django.core.validators.FileExtensionValidator(allowed_extensions=['pdf', 'ppt', 'pptx']),
                        shop.models.validate_proposal_slide_size,
                    ],
                )),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
