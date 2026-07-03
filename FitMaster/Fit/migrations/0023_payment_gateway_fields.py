from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Fit', '0022_seed_sample_products'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='gateway_order_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='gateway_payment_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='gateway_signature',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
