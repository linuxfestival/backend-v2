# Generated by Django 5.1.5 on 2025-03-18 16:32

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_staff'),
    ]

    operations = [
        migrations.RenameField(
            model_name='staff',
            old_name='department',
            new_name='team',
        ),
    ]
