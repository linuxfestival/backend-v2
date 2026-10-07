from django.db import migrations, models


def repair_negative_capacities(apps, schema_editor):
    Presentation = apps.get_model("shop", "Presentation")
    Presentation.objects.filter(capacity__lt=0).update(capacity=0)


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0017_alter_payment_authority_alter_payment_total_price_and_more"),
    ]

    operations = [
        migrations.RunPython(repair_negative_capacities, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="presentation",
            name="capacity",
            field=models.PositiveIntegerField(),
        ),
        migrations.AddConstraint(
            model_name="participation",
            constraint=models.UniqueConstraint(
                fields=("user", "presentation"),
                name="unique_user_presentation",
            ),
        ),
    ]
