from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('shop', '0025_checkout_lifecycle'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [migrations.CreateModel(
        name='CouponRedemption',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('coupon_code', models.CharField(max_length=50)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('snapshot', models.JSONField(default=dict)),
            ('coupon', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='redemptions', to='shop.coupon')),
            ('payment', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='coupon_redemption', to='shop.payment')),
            ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ('participations', models.ManyToManyField(related_name='coupon_redemptions', to='shop.participation')),
        ],
    )]
