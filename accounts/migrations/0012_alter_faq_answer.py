# Generated by Django 5.1.5 on 2025-03-25 12:09

import tinymce.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_alter_faq_answer'),
    ]

    operations = [
        migrations.AlterField(
            model_name='faq',
            name='answer',
            field=tinymce.models.HTMLField(),
        ),
    ]
