from django.conf import settings
from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('shop', '0023_coupon_minimum_items'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Bundle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('description', models.TextField(blank=True)),
                ('price', models.DecimalField(decimal_places=2, max_digits=12, validators=[MinValueValidator(Decimal('0'))])),
                ('is_active', models.BooleanField(default=True)),
                ('presentations', models.ManyToManyField(related_name='bundles', to='shop.presentation')),
                ('tags', models.ManyToManyField(blank=True, related_name='bundles', to='shop.presentationtag')),
            ],
        ),
        migrations.CreateModel(
            name='BundleSelection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('bundle', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='selections', to='shop.bundle')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bundle_selections', to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('user', 'bundle'), name='unique_user_bundle')]},
        ),
        migrations.AddField(
            model_name='participation',
            name='bundle_selection',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.RESTRICT, related_name='participations', to='shop.bundleselection'),
        ),
        migrations.AddField(
            model_name='payment',
            name='bundle_snapshot',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='coupon',
            name='minimum_items',
            field=models.PositiveIntegerField(
                default=1, validators=[MinValueValidator(1)],
                help_text=(
                    'Minimum number of standalone presentations/workshops in the cart. Counts '
                    'pending standalone presentations, including those outside the coupon scope. '
                    'Accessories, bundle members, and previously purchased items do not count.'
                ),
            ),
        ),
    ]
