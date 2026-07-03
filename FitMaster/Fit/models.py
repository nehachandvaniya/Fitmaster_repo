from django.db import models
from django.contrib.auth.hashers import make_password, check_password

# Create your models here.
class User(models.Model):
    ROLE_CHOICES = ( ('admin','Admin'), ('customer','Customer'), ('trainer','Trainer'))
    role = models.CharField(max_length=20, choices=ROLE_CHOICES,null=True,blank=True)
    firstname=models.CharField(max_length=20,blank=True,null=True)
    lastname=models.CharField(max_length=20,blank=True,null=True)
    email=models.EmailField()
    password=models.CharField(max_length=8)
    mobile=models.CharField(max_length=10)
    address=models.CharField(max_length=100)
    state=models.CharField(max_length=20)
    city=models.CharField(max_length=20)
    pincode=models.IntegerField()
    gender=models.CharField(null=True,blank=True)
    profile_pic=models.ImageField(upload_to='customer_images',null=True,blank=True)
   
    # def set_password(self, raw_password):
    #     self.password = make_password(raw_password) 
    
    # def check_password(self, raw_password):
    #     return check_password(raw_password, self.password)
     
class Category(models.Model):
    name=models.CharField(max_length=100)
    image=models.ImageField(upload_to='Category_images')
    def __str__(self):
        return self.name
    
class Product(models.Model):
    name=models.CharField(max_length=100)
    price=models.IntegerField()
    desc=models.TextField()
    stock=models.IntegerField(blank=True, null=True)
    image=models.ImageField(upload_to='pro_images',blank=True, null=True)
    category=models.ForeignKey(Category,on_delete=models.CASCADE,blank=True, null=True)

class Trainer(models.Model):
    CATEGORY_CHOICES = ( ('gym','Gym'), ('yoga','Yoga'), ('zumba','Zumba'))
    users=models.ForeignKey(User,on_delete=models.CASCADE)
    category=models.CharField(choices=CATEGORY_CHOICES)
    experience_year=models.IntegerField()
    specialization=models.CharField(max_length=200)
    qualification=models.CharField(max_length=100)

class Package(models.Model): 
    name = models.CharField(max_length=100) 
    duration_months = models.IntegerField() 
    price = models.DecimalField(max_digits=10, decimal_places=2) 
    description = models.TextField() 
    # created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

class Membership(models.Model):
    customer = models.ForeignKey(User, on_delete=models.CASCADE) 
    package = models.ForeignKey(Package, on_delete=models.CASCADE,default=True) 
    trainer = models.ForeignKey(Trainer, on_delete=models.SET_NULL, null=True) 
    start_date = models.DateField() 
    end_date = models.DateField() 
    status = models.CharField(max_length=20)

class DietPlan(models.Model): 
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE) 
    customer = models.ForeignKey(User, on_delete=models.CASCADE) 
    diet_description = models.TextField() 
    calories = models.IntegerField() 
    created_at = models.DateTimeField(auto_now_add=True)

class ExercisePlan(models.Model):
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE) 
    customer = models.ForeignKey(User, on_delete=models.CASCADE) 
    exercise_name = models.CharField(max_length=100) 
    sets = models.IntegerField() 
    reps = models.IntegerField() 
    instructions = models.TextField()

class FitnessProgress(models.Model): 
    customer = models.ForeignKey(User, on_delete=models.CASCADE) 
    weight = models.FloatField()
    height = models.FloatField() 
    bmi = models.FloatField() 
    record_date = models.DateField()

class Payment(models.Model):
     customer = models.ForeignKey(User, on_delete=models.CASCADE) 
     membership = models.ForeignKey(Membership, on_delete=models.CASCADE) 
     amount = models.DecimalField(max_digits=10, decimal_places=2)
     payment_method = models.CharField(max_length=50) 
     payment_date = models.DateTimeField() 
     status = models.CharField(max_length=20)
     gateway_order_id = models.CharField(max_length=100, null=True, blank=True)
     gateway_payment_id = models.CharField(max_length=100, null=True, blank=True)
     gateway_signature = models.CharField(max_length=255, null=True, blank=True)

class Invoice(models.Model): 
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE) 
    invoice_number = models.CharField(max_length=50) 
    generated_date = models.DateTimeField() 
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

class Feedback(models.Model): 
    customer = models.ForeignKey(User, on_delete=models.CASCADE) 
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE) 
    rating = models.IntegerField() 
    comments = models.TextField() 
    created_at = models.DateTimeField(auto_now_add=True)

class Notice(models.Model): 
    AUDIENCE_CHOICES = (
        ('all', 'Everyone'),
        ('customers', 'All Customers'),
        ('trainers', 'All Trainers'),
        ('specific_customer', 'Specific Customer'),
        ('specific_trainer', 'Specific Trainer'),
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    audience = models.CharField(max_length=30, choices=AUDIENCE_CHOICES, default='all')
    recipient = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_notices')
    send_email = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True) 
    created_at = models.DateTimeField(auto_now_add=True)  

class Cart(models.Model):
    pro=models.ForeignKey(Product,on_delete=models.CASCADE)
    users=models.ForeignKey(User,on_delete=models.CASCADE)
    total_price=models.IntegerField()
    qty=models.IntegerField()
    order_id=models.IntegerField(default=0)
    
class Order(models.Model):
    pro=models.ForeignKey(Product,on_delete=models.CASCADE)
    users=models.ForeignKey(User,on_delete=models.CASCADE)
    qty=models.IntegerField()
    total_price=models.IntegerField()
    first_name=models.CharField(max_length=50)
    mobile=models.IntegerField()
    address=models.TextField()
    city=models.CharField(max_length=40)
    state=models.CharField(max_length=40)
    pincode=models.IntegerField()
    payment_mode=models.CharField(max_length=20)
    transactionid=models.TextField(blank=True, null=True)
    datetime=models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.first_name


class NewsletterSubscription(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


class ContactMessage(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=150)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} - {self.subject}'
