# Generated by Django 5.1.5 on 2025-03-26 14:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0014_accessory_img_accessory_stock_alter_accessory_price'),
        ('shop', '0007_remove_participation_has_accessories_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='accessories',
            field=models.ManyToManyField(related_name='payment_accessories', to='accounts.accessory'),
        ),
    ]
