from django.db import migrations


def seed_sample_trainers(apps, schema_editor):
    User = apps.get_model('Fit', 'User')
    Trainer = apps.get_model('Fit', 'Trainer')

    trainers = [
        {
            'firstname': 'Aarav',
            'lastname': 'Mehta',
            'email': 'aarav.trainer@fitmaster.com',
            'password': 'train123',
            'mobile': '9876543210',
            'address': 'Satellite Road',
            'city': 'Ahmedabad',
            'state': 'Gujarat',
            'pincode': 380015,
            'category': 'gym',
            'experience_year': 6,
            'specialization': 'Strength training and body transformation',
            'qualification': 'Certified Personal Trainer',
        },
        {
            'firstname': 'Riya',
            'lastname': 'Shah',
            'email': 'riya.yoga@fitmaster.com',
            'password': 'train123',
            'mobile': '9876543211',
            'address': 'Navrangpura',
            'city': 'Ahmedabad',
            'state': 'Gujarat',
            'pincode': 380009,
            'category': 'yoga',
            'experience_year': 5,
            'specialization': 'Yoga therapy, flexibility, and breathwork',
            'qualification': 'Diploma in Yoga Education',
        },
        {
            'firstname': 'Kunal',
            'lastname': 'Patel',
            'email': 'kunal.zumba@fitmaster.com',
            'password': 'train123',
            'mobile': '9876543212',
            'address': 'Prahlad Nagar',
            'city': 'Ahmedabad',
            'state': 'Gujarat',
            'pincode': 380015,
            'category': 'zumba',
            'experience_year': 4,
            'specialization': 'Zumba, cardio endurance, and group fitness',
            'qualification': 'Licensed Zumba Instructor',
        },
    ]

    for trainer_data in trainers:
        user, _ = User.objects.get_or_create(
            email=trainer_data['email'],
            defaults={
                'firstname': trainer_data['firstname'],
                'lastname': trainer_data['lastname'],
                'password': trainer_data['password'],
                'mobile': trainer_data['mobile'],
                'address': trainer_data['address'],
                'city': trainer_data['city'],
                'state': trainer_data['state'],
                'pincode': trainer_data['pincode'],
                'role': 'trainer',
            },
        )

        user.role = 'trainer'
        user.firstname = trainer_data['firstname']
        user.lastname = trainer_data['lastname']
        user.mobile = trainer_data['mobile']
        user.address = trainer_data['address']
        user.city = trainer_data['city']
        user.state = trainer_data['state']
        user.pincode = trainer_data['pincode']
        user.password = trainer_data['password']
        user.save()

        Trainer.objects.get_or_create(
            users=user,
            defaults={
                'category': trainer_data['category'],
                'experience_year': trainer_data['experience_year'],
                'specialization': trainer_data['specialization'],
                'qualification': trainer_data['qualification'],
            },
        )


def remove_sample_trainers(apps, schema_editor):
    User = apps.get_model('Fit', 'User')
    Trainer = apps.get_model('Fit', 'Trainer')

    emails = [
        'aarav.trainer@fitmaster.com',
        'riya.yoga@fitmaster.com',
        'kunal.zumba@fitmaster.com',
    ]

    trainers = Trainer.objects.filter(users__email__in=emails)
    users = User.objects.filter(email__in=emails)
    trainers.delete()
    users.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('Fit', '0023_payment_gateway_fields'),
    ]

    operations = [
        migrations.RunPython(seed_sample_trainers, remove_sample_trainers),
    ]
