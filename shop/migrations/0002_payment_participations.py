# Generated by Django 5.1.5 on 2025-01-30 18:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='participations',
            field=models.ManyToManyField(related_name='payments', to='shop.participation'),
        ),
    ]
