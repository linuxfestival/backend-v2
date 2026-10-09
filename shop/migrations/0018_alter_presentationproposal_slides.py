import django.core.validators
from django.db import migrations, models
import shop.models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0017_presentationproposal'),
    ]

    operations = [
        migrations.AlterField(
            model_name='presentationproposal',
            name='slides',
            field=models.FileField(
                blank=True,
                upload_to='presentation_proposals/',
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=['pdf', 'ppt', 'pptx'],
                    ),
                    shop.models.validate_proposal_slide_size,
                ],
            ),
        ),
    ]
