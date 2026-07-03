from django.contrib import admin

from .models import (
    Cart,
    Category,
    ContactMessage,
    DietPlan,
    ExercisePlan,
    Feedback,
    FitnessProgress,
    Invoice,
    Membership,
    NewsletterSubscription,
    Notice,
    Order,
    Package,
    Payment,
    Product,
    Trainer,
    User,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['id', 'firstname', 'lastname', 'email', 'mobile', 'role', 'city', 'state']
    list_filter = ['role', 'state', 'city']
    search_fields = ['firstname', 'lastname', 'email', 'mobile']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'image']
    search_fields = ['name']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'category', 'price', 'stock']
    list_filter = ['category']
    search_fields = ['name', 'desc']


@admin.register(Trainer)
class TrainerAdmin(admin.ModelAdmin):
    list_display = ['id', 'users', 'category', 'experience_year', 'specialization', 'qualification']
    list_filter = ['category']
    search_fields = ['users__firstname', 'users__lastname', 'users__email', 'specialization', 'qualification']


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'duration_months', 'price', 'description']
    search_fields = ['name', 'description']


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'package', 'trainer', 'start_date', 'end_date', 'status']
    list_filter = ['status', 'package']
    search_fields = ['customer__firstname', 'customer__lastname', 'customer__email']


@admin.register(DietPlan)
class DietPlanAdmin(admin.ModelAdmin):
    list_display = ['id', 'trainer', 'customer', 'calories', 'created_at']
    list_filter = ['trainer']
    search_fields = ['customer__firstname', 'customer__lastname', 'diet_description']


@admin.register(ExercisePlan)
class ExercisePlanAdmin(admin.ModelAdmin):
    list_display = ['id', 'trainer', 'customer', 'exercise_name', 'sets', 'reps']
    list_filter = ['trainer']
    search_fields = ['customer__firstname', 'customer__lastname', 'exercise_name', 'instructions']


@admin.register(FitnessProgress)
class FitnessProgressAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'weight', 'height', 'bmi', 'record_date']
    list_filter = ['record_date']
    search_fields = ['customer__firstname', 'customer__lastname', 'customer__email']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'membership', 'amount', 'payment_method', 'payment_date', 'status']
    list_filter = ['status', 'payment_method']
    search_fields = ['customer__firstname', 'customer__lastname', 'gateway_order_id', 'gateway_payment_id']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['id', 'payment', 'invoice_number', 'generated_date', 'total_amount']
    search_fields = ['invoice_number', 'payment__customer__firstname', 'payment__customer__lastname']


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'trainer', 'rating', 'created_at']
    list_filter = ['rating']
    search_fields = ['customer__firstname', 'customer__lastname', 'comments']


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'audience', 'recipient', 'send_email', 'email_sent_at', 'created_by', 'created_at']
    list_filter = ['audience', 'send_email']
    search_fields = ['title', 'message', 'recipient__email', 'recipient__firstname', 'recipient__lastname']


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['id', 'pro', 'users', 'total_price', 'qty', 'order_id']
    search_fields = ['users__firstname', 'users__lastname', 'pro__name']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'pro', 'users', 'total_price', 'first_name', 'qty', 'payment_mode', 'datetime']
    list_filter = ['payment_mode']
    search_fields = ['first_name', 'users__firstname', 'users__lastname', 'pro__name', 'transactionid']


@admin.register(NewsletterSubscription)
class NewsletterSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['id', 'email', 'created_at']
    search_fields = ['email']


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'email', 'phone', 'subject', 'created_at']
    search_fields = ['name', 'email', 'phone', 'subject', 'message']
