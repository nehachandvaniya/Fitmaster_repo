from django.db import migrations


def seed_demo_packages(apps, schema_editor):
    Package = apps.get_model('Fit', 'Package')

    packages = [
        {
            'name': 'Starter Fit',
            'duration_months': 1,
            'price': 999.00,
            'description': 'A one-month beginner package for users starting their fitness journey with gym floor access and basic guidance.',
        },
        {
            'name': 'Transformation Plus',
            'duration_months': 3,
            'price': 2499.00,
            'description': 'A three-month plan designed for consistent progress with structured workouts, trainer support, and better routine tracking.',
        },
        {
            'name': 'Elite Annual',
            'duration_months': 12,
            'price': 7999.00,
            'description': 'A full-year premium membership for long-term results with priority access, trainer assignment, and progress-focused support.',
        },
    ]

    for package_data in packages:
        Package.objects.get_or_create(
            name=package_data['name'],
            defaults={
                'duration_months': package_data['duration_months'],
                'price': package_data['price'],
                'description': package_data['description'],
            },
        )


def remove_demo_packages(apps, schema_editor):
    Package = apps.get_model('Fit', 'Package')
    Package.objects.filter(name__in=['Starter Fit', 'Transformation Plus', 'Elite Annual']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('Fit', '0024_seed_sample_trainers'),
    ]

    operations = [
        migrations.RunPython(seed_demo_packages, remove_demo_packages),
    ]
