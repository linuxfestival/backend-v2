from django.db import migrations, models


def populate_persian_names(apps, schema_editor):
    PresentationTag = apps.get_model("shop", "PresentationTag")
    translations = {
        "Online": "آنلاین",
        "In-Person": "حضوری",
        "Beginner": "مبتدی",
        "Intermediate": "متوسط",
        "Advanced": "پیشرفته",
    }
    for tag in PresentationTag.objects.all():
        tag.fa_name = translations.get(tag.en_name, tag.en_name)
        tag.save(update_fields=["fa_name"])


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0018_launch_safety_constraints"),
    ]

    operations = [
        migrations.RenameField(
            model_name="presentationtag",
            old_name="name",
            new_name="en_name",
        ),
        migrations.AddField(
            model_name="presentationtag",
            name="fa_name",
            field=models.CharField(default="", max_length=63),
            preserve_default=False,
        ),
        migrations.RunPython(populate_persian_names, migrations.RunPython.noop),
    ]
