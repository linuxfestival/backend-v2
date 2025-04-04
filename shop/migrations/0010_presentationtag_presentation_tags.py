# Generated by Django 5.1.5 on 2025-03-27 20:14

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0009_alter_presentation_description_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='PresentationTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=63)),
            ],
        ),
        migrations.AddField(
            model_name='presentation',
            name='tags',
            field=models.ManyToManyField(related_name='presentation_tag', to='shop.presentationtag'),
        ),
    ]
