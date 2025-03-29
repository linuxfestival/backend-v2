# Generated by Django 5.1.5 on 2025-03-29 12:17

import tinymce.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0014_presentation_morkopoloyor_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='presentation',
            old_name='description',
            new_name='en_description',
        ),
        migrations.RenameField(
            model_name='presentation',
            old_name='title',
            new_name='en_title',
        ),
        migrations.AddField(
            model_name='presentation',
            name='fa_description',
            field=tinymce.models.HTMLField(default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='presentation',
            name='fa_title',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
    ]
