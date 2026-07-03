from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('Fit', '0026_newslettersubscription'),
    ]

    operations = [
        migrations.AddField(
            model_name='notice',
            name='audience',
            field=models.CharField(choices=[('all', 'Everyone'), ('customers', 'All Customers'), ('trainers', 'All Trainers'), ('specific_customer', 'Specific Customer'), ('specific_trainer', 'Specific Trainer')], default='all', max_length=30),
        ),
        migrations.AddField(
            model_name='notice',
            name='email_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='notice',
            name='recipient',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='received_notices', to='Fit.user'),
        ),
        migrations.AddField(
            model_name='notice',
            name='send_email',
            field=models.BooleanField(default=False),
        ),
    ]
