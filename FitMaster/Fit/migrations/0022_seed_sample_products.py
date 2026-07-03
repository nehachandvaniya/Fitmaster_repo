from django.db import migrations


def seed_sample_products(apps, schema_editor):
    Category = apps.get_model('Fit', 'Category')
    Product = apps.get_model('Fit', 'Product')

    categories = {
        'Supplements': {'image': ''},
        'Equipment': {'image': ''},
        'Accessories': {'image': ''},
    }

    category_objects = {}
    for name, defaults in categories.items():
        category, _ = Category.objects.get_or_create(name=name, defaults=defaults)
        category_objects[name] = category

    products = [
        {
            'name': 'Whey Protein Gold',
            'price': 2499,
            'desc': 'Premium whey protein powder for muscle recovery and strength support.',
            'stock': 20,
            'category': 'Supplements',
        },
        {
            'name': 'Mass Gainer Plus',
            'price': 1899,
            'desc': 'High-calorie blend designed to support healthy weight and muscle gain.',
            'stock': 15,
            'category': 'Supplements',
        },
        {
            'name': 'Yoga Mat Pro',
            'price': 899,
            'desc': 'Anti-slip exercise mat suitable for yoga, pilates, and stretching routines.',
            'stock': 25,
            'category': 'Equipment',
        },
        {
            'name': 'Adjustable Dumbbell Set',
            'price': 4599,
            'desc': 'Compact dumbbell set for versatile home strength training workouts.',
            'stock': 10,
            'category': 'Equipment',
        },
        {
            'name': 'Resistance Band Kit',
            'price': 699,
            'desc': 'Multi-level resistance bands ideal for mobility, rehab, and strength sessions.',
            'stock': 30,
            'category': 'Accessories',
        },
        {
            'name': 'Gym Shaker Bottle',
            'price': 299,
            'desc': 'Leak-resistant shaker bottle for protein drinks and hydration on the go.',
            'stock': 40,
            'category': 'Accessories',
        },
    ]

    for product in products:
        Product.objects.get_or_create(
            name=product['name'],
            defaults={
                'price': product['price'],
                'desc': product['desc'],
                'stock': product['stock'],
                'category': category_objects[product['category']],
                'image': '',
            },
        )


def remove_sample_products(apps, schema_editor):
    Product = apps.get_model('Fit', 'Product')
    Category = apps.get_model('Fit', 'Category')

    product_names = [
        'Whey Protein Gold',
        'Mass Gainer Plus',
        'Yoga Mat Pro',
        'Adjustable Dumbbell Set',
        'Resistance Band Kit',
        'Gym Shaker Bottle',
    ]

    Product.objects.filter(name__in=product_names).delete()
    Category.objects.filter(name__in=['Supplements', 'Equipment', 'Accessories']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('Fit', '0021_rename_user_cart_users'),
    ]

    operations = [
        migrations.RunPython(seed_sample_products, remove_sample_products),
    ]
