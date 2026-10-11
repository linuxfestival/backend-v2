from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('shop', '0024_presentation_bundles')]

    operations = [
        migrations.AddField(model_name='payment', name='checkout_snapshot', field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='payment', name='superseded_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='payment', name='superseded_reason', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='payment', name='requires_manual_review', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='payment', name='review_resolved', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='payment', name='review_notes', field=models.TextField(blank=True, help_text='Support notes; changing this does not refund or fulfil a payment.')),
        migrations.AddField(model_name='payment', name='last_reconciled_at', field=models.DateTimeField(blank=True, null=True)),
    ]
