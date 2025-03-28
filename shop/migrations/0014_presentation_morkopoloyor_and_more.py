# Generated by Django 5.1.5 on 2025-03-28 17:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0013_presentationtag_color'),
    ]

    operations = [
        migrations.AddField(
            model_name='presentation',
            name='morkopoloyor',
            field=models.URLField(blank=True),
        ),
        migrations.AlterField(
            model_name='presentation',
            name='service_type',
            field=models.CharField(choices=[('WORKSHOP', 'WORKSHOP'), ('TALK', 'TALK'), ('PACKAGE', 'PACKAGE')], max_length=30),
        ),
    ]
