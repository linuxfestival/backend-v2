from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('shop', '0022_validate_proposal_slide_content')]

    operations = [
        migrations.AddField(
            model_name='coupon',
            name='minimum_items',
            field=models.PositiveIntegerField(
                default=1,
                validators=[MinValueValidator(1)],
                help_text=(
                    'Minimum number of presentations/workshops in the cart. Counts all '
                    'pending cart presentations, including those outside the coupon scope. '
                    'Accessories and previously purchased items do not count.'
                ),
            ),
        ),
    ]
