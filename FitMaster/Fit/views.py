from functools import wraps
from decimal import Decimal
from types import SimpleNamespace

from django.shortcuts import render, redirect
from django.db import models, transaction
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import *
from datetime import date, datetime, timedelta
from .form import ProductSearchForm
from django.conf import settings
from django.contrib.auth import authenticate, login as django_login
from django.utils.crypto import constant_time_compare

from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.mail import send_mail
from .models import *


def _normalize_email(value):
    return (value or '').strip().lower()


def _forgot_password_context(role_label, login_url_name, reset_url_name, account_email=''):
    return {
        'role_label': role_label,
        'login_url_name': login_url_name,
        'reset_url_name': reset_url_name,
        'account_email': account_email,
    }


def _get_notice_recipients(notice):
    if notice.audience == 'all':
        return User.objects.filter(role__in=['customer', 'trainer']).exclude(email='').exclude(email__isnull=True)
    if notice.audience == 'customers':
        return User.objects.filter(role='customer').exclude(email='').exclude(email__isnull=True)
    if notice.audience == 'trainers':
        return User.objects.filter(role='trainer').exclude(email='').exclude(email__isnull=True)
    if notice.audience == 'specific_customer':
        return User.objects.filter(id=notice.recipient_id, role='customer').exclude(email='').exclude(email__isnull=True)
    if notice.audience == 'specific_trainer':
        return User.objects.filter(id=notice.recipient_id, role='trainer').exclude(email='').exclude(email__isnull=True)
    return User.objects.none()


def _send_notice_email(notice):
    recipients = list(_get_notice_recipients(notice).values_list('email', flat=True))
    if not recipients:
        return False, 'No valid recipients found for this notification.'

    try:
        send_mail(
            subject=notice.title,
            message=notice.message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@fitmaster.com'),
            recipient_list=recipients,
            fail_silently=False,
        )
        notice.email_sent_at = timezone.now()
        notice.save(update_fields=['email_sent_at'])
        return True, f'Notification email sent to {len(recipients)} recipient(s).'
    except Exception:
        return False, 'Notice saved, but email delivery could not be completed. Configure your email backend to send real emails.'


def _get_visible_notices_for_user(user, role=None):
    resolved_role = role or user.role
    if resolved_role not in ['customer', 'trainer']:
        if Trainer.objects.filter(users=user).exists():
            resolved_role = 'trainer'
        else:
            resolved_role = 'customer'

    role_filter = 'specific_customer' if resolved_role == 'customer' else 'specific_trainer'
    role_group = 'customers' if resolved_role == 'customer' else 'trainers'
    return Notice.objects.filter(
        models.Q(audience='all') |
        models.Q(audience=role_group) |
        models.Q(audience=role_filter, recipient=user)
    ).select_related('created_by', 'recipient').order_by('-created_at')


def subscribe_newsletter(request):
    if request.method != 'POST':
        return redirect('index')

    email = request.POST.get('newsletter_email', '').strip()
    next_url = request.POST.get('next', '').strip() or request.META.get('HTTP_REFERER') or '/'

    if not email:
        messages.error(request, 'Please enter your email address for the newsletter.')
        return redirect(next_url)

    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, 'Please enter a valid email address.')
        return redirect(next_url)

    _, created = NewsletterSubscription.objects.get_or_create(email=email)
    if created:
        messages.success(request, 'You have been subscribed to the newsletter successfully.')
    else:
        messages.info(request, 'This email is already subscribed to the newsletter.')

    return redirect(next_url)


def contact_page(request):
    initial_name = ''
    initial_email = ''
    initial_phone = ''

    if request.session.get('login'):
        user = User.objects.filter(email=request.session['login']).first()
        if user:
            initial_name = f'{user.firstname or ""} {user.lastname or ""}'.strip()
            initial_email = user.email or ''
            initial_phone = user.mobile or ''

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        subject = request.POST.get('subject', '').strip()
        message_text = request.POST.get('message', '').strip()

        if not all([name, email, subject, message_text]):
            messages.error(request, 'Please fill in all required contact fields.')
            return render(request, 'contact.html', {
                'login': bool(request.session.get('login')),
                'initial_name': name,
                'initial_email': email,
                'initial_phone': phone,
            })

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Please enter a valid email address.')
            return render(request, 'contact.html', {
                'login': bool(request.session.get('login')),
                'initial_name': name,
                'initial_email': email,
                'initial_phone': phone,
            })

        ContactMessage.objects.create(
            name=name,
            email=email,
            phone=phone,
            subject=subject,
            message=message_text,
        )
        messages.success(request, 'Your message has been sent successfully. We will get back to you soon.')
        return redirect('contact_page')

    return render(request, 'contact.html', {
        'login': bool(request.session.get('login')),
        'initial_name': initial_name,
        'initial_email': initial_email,
        'initial_phone': initial_phone,
    })


def _create_membership_records(user, package, trainer, payment_method, payment_status, gateway_data=None):
    start_date = date.today()
    end_date = start_date + timedelta(days=package.duration_months * 30)

    membership = Membership.objects.create(
        customer=user,
        package=package,
        trainer=trainer,
        start_date=start_date,
        end_date=end_date,
        status='Active'
    )

    payment = Payment.objects.create(
        customer=user,
        membership=membership,
        amount=package.price,
        payment_method=payment_method,
        payment_date=timezone.now(),
        status=payment_status,
        gateway_order_id=(gateway_data or {}).get('order_id'),
        gateway_payment_id=(gateway_data or {}).get('payment_id'),
        gateway_signature=(gateway_data or {}).get('signature'),
    )

    Invoice.objects.create(
        payment=payment,
        invoice_number=f"INV-{payment.id:05d}",
        generated_date=timezone.now(),
        total_amount=package.price
    )

    return membership, payment


def _get_active_membership(user):
    return (
        Membership.objects.filter(
            customer=user,
            status__iexact='Active',
            end_date__gte=date.today()
        )
        .select_related('package', 'trainer', 'trainer__users')
        .order_by('-end_date', '-id')
        .first()
    )


def _create_store_orders(user, cart_items, checkout_data, payment_mode, transaction_id=None):
    created_orders = []

    for item in cart_items:
        if getattr(item, 'pro', None) is None:
            continue

        uses_saved_cart = hasattr(item, 'order_id')

        if not uses_saved_cart:
            latest_product = Product.objects.get(id=item.pro.id)
            if latest_product.stock is None or latest_product.stock < item.qty:
                raise ValueError(f'Only {latest_product.stock or 0} item(s) available for {latest_product.name}.')

        order = Order.objects.create(
            pro=item.pro,
            users=user,
            qty=item.qty,
            total_price=item.total_price,
            first_name=checkout_data['first_name'],
            mobile=checkout_data['mobile'],
            address=checkout_data['address'],
            city=checkout_data['city'],
            state=checkout_data['state'],
            pincode=checkout_data['pincode'],
            payment_mode=payment_mode,
            transactionid=transaction_id,
        )
        if uses_saved_cart:
            item.order_id = order.id
            item.save()
        else:
            latest_product.stock -= item.qty
            latest_product.save()
        created_orders.append(order)

    return created_orders


def _get_buy_now_checkout_item(request):
    buy_now_data = request.session.get('buy_now_checkout')
    if not buy_now_data:
        return []

    product_id = buy_now_data.get('product_id')
    qty = int(buy_now_data.get('qty', 0) or 0)
    if not product_id or qty <= 0:
        request.session.pop('buy_now_checkout', None)
        request.session.modified = True
        return []

    product = Product.objects.filter(id=product_id).first()
    if not product:
        request.session.pop('buy_now_checkout', None)
        request.session.modified = True
        return []

    return [
        SimpleNamespace(
            pro=product,
            qty=qty,
            total_price=product.price * qty,
        )
    ]


def _get_checkout_items(request, user):
    buy_now_items = _get_buy_now_checkout_item(request)
    if buy_now_items:
        total = sum(item.total_price for item in buy_now_items)
        return buy_now_items, total, 'buy_now'

    cart_items = Cart.objects.filter(users=user, order_id=0).select_related('pro')
    total = sum(item.total_price for item in cart_items)
    return cart_items, total, 'cart'


def _get_trainer_memberships(trainer):
    return Membership.objects.filter(trainer=trainer).select_related('customer', 'package').order_by('-start_date', '-id')


def _get_assigned_customer(trainer, customer_id):
    membership = Membership.objects.filter(trainer=trainer, customer_id=customer_id).select_related('customer').first()
    return membership.customer if membership else None


def admin_required(view_func):
    @never_cache
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
            return view_func(request, *args, **kwargs)

        if request.session.get('user_role') == 'admin' and request.session.get('admin_login'):
            return view_func(request, *args, **kwargs)

        messages.error(request, 'Please log in as admin to access this page.')
        return redirect('admin_login')

    return _wrapped_view


def trainer_required(view_func):
    @never_cache
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        trainer_id = request.session.get('trainer_login')
        if trainer_id and Trainer.objects.filter(id=trainer_id).exists():
            return view_func(request, *args, **kwargs)

        messages.error(request, 'Please log in as trainer to access this page.')
        return redirect('login')

    return _wrapped_view


def customer_required(view_func):
    @never_cache
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.session.get('login'):
            return view_func(request, *args, **kwargs)

        messages.error(request, 'Please log in to access this page.')
        return redirect('login')

    return _wrapped_view


def _get_logged_trainer(request):
    return Trainer.objects.select_related('users').get(id=request.session['trainer_login'])

@transaction.atomic
def register(request):
    if request.method == 'POST':
        email = _normalize_email(request.POST.get('email'))
        role = request.POST.get('role', 'customer')

        if role == 'trainer':
            return redirect('trainer_register')

        if role != 'customer':
            return render(
                request,
                'Userregister.html',
                {'registered': "Only customer accounts can be created from this page."}
            )

        if not email:
            return render(
                request,
                'Userregister.html',
                {'registered': "Email is required."}
            )

        if User.objects.filter(email__iexact=email).exists():
            return render(
                request,
                'Userregister.html',
                {'registered': "An account with this email already exists. Please sign in or reset your password."}
            )

        obj = User()
        obj.email = email
        obj.firstname = request.POST.get('firstname', '')
        obj.lastname = request.POST.get('lastname', '')
        obj.password = request.POST['password']
        obj.mobile = request.POST.get('mobile', '')
        obj.address = request.POST.get('address', '')
        obj.city = request.POST['city']
        obj.state = request.POST['state']
        obj.pincode = request.POST['pincode']
        obj.role = role
        obj.save()

        if role == 'trainer':
            trainer = Trainer()
            trainer.users = obj
            trainer.category = request.POST['category']
            trainer.experience_year = request.POST['experience_year']
            trainer.specialization = request.POST['specialization']
            trainer.qualification = request.POST['qualification']
            trainer.save()

        messages.success(request, "Registration successful! Please sign in to continue.")
        return redirect('login')
    else:
        return render(request, 'Userregister.html')


@transaction.atomic
def trainer_register(request):
    if request.method == 'POST':
        email = _normalize_email(request.POST.get('email'))
        if not email:
            return render(
                request,
                'trainer_register.html',
                {'registered': "Email is required."}
            )

        if User.objects.filter(email__iexact=email).exists():
            return render(
                request,
                'trainer_register.html',
                {'registered': "An account with this email already exists. Please sign in or reset your password."}
            )

        user = User()
        user.firstname = request.POST.get('firstname', '')
        user.lastname = request.POST.get('lastname', '')
        user.email = email
        user.password = request.POST['password']
        user.mobile = request.POST.get('mobile', '')
        user.address = request.POST.get('address', '')
        user.city = request.POST['city']
        user.state = request.POST['state']
        user.pincode = request.POST['pincode']
        user.role = 'trainer'
        user.save()

        trainer = Trainer()
        trainer.users = user
        trainer.category = request.POST['category']
        trainer.experience_year = request.POST['experience_year']
        trainer.specialization = request.POST['specialization']
        trainer.qualification = request.POST['qualification']
        trainer.save()

        messages.success(request, "Trainer registration successful! Please sign in to continue.")
        return redirect('login')
    return render(request, 'trainer_register.html')


def customer_change_password(request):
    if 'login' not in request.session:
        messages.error(request, 'Please login first to change your password.')
        return redirect('login')

    user = User.objects.filter(email__iexact=request.session.get('login'), role='customer').first()
    if user is None:
        messages.error(request, 'Customer account not found.')
        return redirect('login')

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if new_password != confirm_password:
            return render(request, 'change_password.html', {
                'Error': 'New password and confirm password do not match.',
                'role_label': 'Customer',
                'login_url_name': 'login',
                'account_email': user.email,
            })

        user.password = new_password
        user.save()
        return render(request, 'login.html', {'saved': 'Password changed successfully. Please log in.'})

    return render(request, 'change_password.html', {
        'role_label': 'Customer',
        'login_url_name': 'login',
        'account_email': user.email,
    })


def trainer_change_password(request):
    trainer_id = request.session.get('trainer_login')
    if not trainer_id:
        messages.error(request, 'Please login first to change your password.')
        return redirect('trainer_login')

    trainer = Trainer.objects.select_related('users').filter(id=trainer_id).first()
    user = trainer.users if trainer else None
    if user is None or user.role != 'trainer':
        messages.error(request, 'Trainer account not found.')
        return redirect('trainer_login')

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if new_password != confirm_password:
            return render(request, 'change_password.html', {
                'Error': 'New password and confirm password do not match.',
                'role_label': 'Trainer',
                'login_url_name': 'trainer_login',
                'account_email': user.email,
            })

        user.password = new_password
        user.save()
        return render(request, 'login.html', {'saved': 'Password changed successfully. Please log in.'})

    return render(request, 'change_password.html', {
        'role_label': 'Trainer',
        'login_url_name': 'trainer_login',
        'account_email': user.email,
    })


def forgot_customer_password(request):
    role_label = 'Customer'
    login_url_name = 'login'
    reset_url_name = 'forgot_customer_password'

    if request.method == 'POST':
        email = _normalize_email(request.POST.get('email'))
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        user = User.objects.filter(email__iexact=email, role='customer').first()
        if user is None:
            return render(request, 'forgot_password.html', {
                **_forgot_password_context(role_label, login_url_name, reset_url_name, account_email=email),
                'Error': 'Customer account not found for that email.',
            })

        if not new_password or not confirm_password:
            return render(request, 'forgot_password.html', {
                **_forgot_password_context(role_label, login_url_name, reset_url_name, account_email=email),
                'Error': 'Please enter both password fields.',
            })

        if new_password != confirm_password:
            return render(request, 'forgot_password.html', {
                **_forgot_password_context(role_label, login_url_name, reset_url_name, account_email=email),
                'Error': 'New password and confirm password do not match.',
            })

        user.password = new_password
        user.save()
        return render(request, 'login.html', {'saved': 'Password reset successfully. Please log in.'})

    return render(request, 'forgot_password.html', _forgot_password_context(role_label, login_url_name, reset_url_name))


def forgot_trainer_password(request):
    role_label = 'Trainer'
    login_url_name = 'trainer_login'
    reset_url_name = 'forgot_trainer_password'

    if request.method == 'POST':
        email = _normalize_email(request.POST.get('email'))
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        user = User.objects.filter(email__iexact=email, role='trainer').first()
        if user is None:
            return render(request, 'forgot_password.html', {
                **_forgot_password_context(role_label, login_url_name, reset_url_name, account_email=email),
                'Error': 'Trainer account not found for that email.',
            })

        if not new_password or not confirm_password:
            return render(request, 'forgot_password.html', {
                **_forgot_password_context(role_label, login_url_name, reset_url_name, account_email=email),
                'Error': 'Please enter both password fields.',
            })

        if new_password != confirm_password:
            return render(request, 'forgot_password.html', {
                **_forgot_password_context(role_label, login_url_name, reset_url_name, account_email=email),
                'Error': 'New password and confirm password do not match.',
            })

        user.password = new_password
        user.save()
        return render(request, 'trainer_login.html', {'saved': 'Password reset successfully. Please log in.'})

    return render(request, 'forgot_password.html', _forgot_password_context(role_label, login_url_name, reset_url_name))


@never_cache
@ensure_csrf_cookie
def admin_login(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        configured_username = settings.ADMIN_LOGIN_USERNAME
        configured_password = settings.ADMIN_LOGIN_PASSWORD
        if (
            configured_password
            and constant_time_compare(username, configured_username)
            and constant_time_compare(password, configured_password)
        ):
            request.session.cycle_key()
            request.session['admin_login'] = username
            request.session['user_role'] = 'admin'
            return redirect('dash')

        user = authenticate(request, username=username, password=password)

        if user is not None and (user.is_staff or user.is_superuser):
            django_login(request, user)
            request.session['admin_login'] = username
            request.session['user_role'] = 'admin'
            return redirect('dash')

        response = render(request, 'admin_login.html', {'Error': "Invalid admin username or password."})
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    response = render(request, 'admin_login.html')
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response
    
def login(request):
    if request.method == 'POST':
        email = _normalize_email(request.POST.get('email'))
        password = request.POST.get('password', '')
        try:
            registered = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return render(
                request,
                'login.html',
                {'Not_registered': "No account with this email was found on this site. Check the email address or make sure you are using the same site where you registered."}
            )

        if registered.role == 'admin':
            return render(request, 'login.html', {'Error': "Admin login is allowed only from the admin login page."})

        if registered.password != password:
            return render(request, 'login.html', {'Error': "Invalid email or password."})

        trainer = None
        if registered.role == 'trainer':
            trainer = Trainer.objects.filter(users=registered).first()
            if trainer is None:
                return render(
                    request,
                    'login.html',
                    {'Error': "This account exists, but its trainer profile is missing. Please contact the site administrator."}
                )

        request.session['user_id'] = registered.id
        request.session['user_role'] = registered.role
        if trainer is not None:
            request.session['trainer_login'] = trainer.id
            request.session['trainer_email'] = registered.email
            return redirect('trainerdash')

        request.session['login'] = registered.email
        membership = _get_active_membership(registered)
        if membership is None:
            messages.info(request, 'Please purchase a membership to start your fitness journey.')
            return redirect('usermember')
        return redirect('index')
    else:
       return render(request,'login.html')


def trainer_login(request):
    messages.info(request, 'Trainer accounts now use the main login page.')
    return redirect('login')

@never_cache
def logout(request):
    redirect_to = 'login'

    if 'admin_login' in request.session or request.session.get('user_role') == 'admin':
        redirect_to = 'admin_login'
    elif 'trainer_login' in request.session:
        redirect_to = 'login'

    request.session.flush()
    return redirect(redirect_to)

@never_cache
@ensure_csrf_cookie
def index(request):
    trainers = list(Trainer.objects.select_related('users').all())
    packages = list(Package.objects.all())
    prod = list(Product.objects.all()[:10])
    product_slides = [prod[index:index + 4] for index in range(0, len(prod), 4)]
    testimonials = list(
        Feedback.objects.select_related('customer', 'trainer', 'trainer__users').order_by('-created_at')[:6]
    )
    trainer_cards = []
    for trainer in trainers:
        feedbacks = Feedback.objects.filter(trainer=trainer)
        rating = 0
        feedback_count = feedbacks.count()
        if feedback_count:
            rating = round(sum(item.rating for item in feedbacks) / feedback_count, 1)

        trainer_cards.append({
            'id': trainer.id,
            'name': f"{trainer.users.firstname or ''} {trainer.users.lastname or ''}".strip() or trainer.users.email,
            'specialty': trainer.get_category_display(),
            'experience': trainer.experience_year,
            'qualification': trainer.qualification,
            'specialization': trainer.specialization,
            'rating': rating,
            'feedback_count': feedback_count,
        })

    context = {
        'trainer': trainers,
        'Pack': packages,
        'featured_trainers': trainer_cards[:6],
        'available_packages': packages,
        'prod': prod,
        'product_slides': product_slides,
        'testimonials': testimonials,
    }
    if 'login' in request.session:
        user = User.objects.filter(email=request.session['login']).first()
        context['login'] = True
        if user:
            active_membership = _get_active_membership(user)
            latest_progress = FitnessProgress.objects.filter(customer=user).order_by('-record_date', '-id').first()
            cart_items = Cart.objects.filter(users=user, order_id=0).select_related('pro')
            orders = Order.objects.filter(users=user)
            notices = _get_visible_notices_for_user(user, role='customer')[:3]

            context.update({
                'home_user': user,
                'active_membership': active_membership,
                'latest_progress': latest_progress,
                'pending_cart_count': cart_items.count(),
                'cart_total': sum(item.total_price for item in cart_items),
                'order_count': orders.count(),
                'recent_products': prod[:4],
                'home_notices': notices,
            })

    response = render(request, 'index.html', context)
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response

def store(request, ):
    cat = Category.objects.all()
    prod = Product.objects.all()[:6]

    if 'login' in request.session:
        return render(request, 'store.html', { 'cat': cat,
        'login':True,
        'products': prod,})
    else:
        return render(request, 'store.html',{ 'cat': cat,'products': prod,})

def product(request, id):
    category = Category.objects.filter(id=id).first()
    pro = Product.objects.filter(category=id)
    if 'login' in request.session:
        return render(request, 'prod.html', {'pro': pro, 'category': category, 'login': True})
    else:
        return render(request, 'prod.html', {'pro': pro, 'category': category})

def product_search(request):
    if request.method == 'GET':
       form = ProductSearchForm(request.GET)
       if form.is_valid():
           search_query = form.cleaned_data['search_query']
           # Perform search in the database
           results = Product.objects.filter(name__icontains=search_query)
           context = {
               'results': results,
               'search_query': search_query,
           }
           if 'login' in request.session:
               context['login'] = True
           return render(request, 'search_result.html', context)
    return redirect('store')

def product_detail(request,id):
   pro = Product.objects.get(id=id)
   related_products = list(
      Product.objects.filter(category=pro.category).exclude(id=pro.id)[:4]
   )
   if len(related_products) < 4:
      fallback_products = Product.objects.exclude(id=pro.id)
      if pro.category_id:
         fallback_products = fallback_products.exclude(category=pro.category)
      fallback_products = list(fallback_products[: 4 - len(related_products)])
      related_products.extend(fallback_products)

   if request.method == 'POST':
      if 'login' in request.session:
         qty = int(request.POST.get('qty', 1) or 1)
         action = request.POST.get('action', 'cart')

         if qty <= 0:
            messages.error(request, 'Please choose a valid quantity.')
            return redirect('product_detail', id=pro.id)

         if pro.stock is not None and qty > pro.stock:
            messages.error(request, f'Only {pro.stock} item(s) are available right now.')
            return redirect('product_detail', id=pro.id)

         users = User.objects.get(email=request.session['login'])

         if action == 'buy':
            request.session['buy_now_checkout'] = {
               'product_id': pro.id,
               'qty': qty,
            }
            request.session.modified = True
            return redirect('checkout')

         store_cart = Cart()
         store_cart.pro = pro
         store_cart.users = users
         store_cart.total_price = pro.price * qty
         store_cart.qty = qty
         store_cart.save()
         if pro.stock is not None:
            pro.stock -= qty
            pro.save()
         messages.success(request, 'Product added to cart.')
         return redirect('product_detail', id=pro.id)
      else:
          # Pass login=False when user is not logged in
         return render(request, 'prodetail.html', {'pro': pro, 'login': False, 'related_products': related_products})
   else:
       # For GET request, check if user is logged in
       if 'login' in request.session:
         return render(request, 'prodetail.html', {'pro': pro, 'login': True, 'related_products': related_products})
       else:
         return render(request, 'prodetail.html', {'pro': pro, 'login': False, 'related_products': related_products})

def cart_view(request):
    if 'login' in request.session:
        user_data = User.objects.get(email=request.session['login'])
        cart_data = Cart.objects.filter(users=user_data, order_id=0)
        total = 0
        for i in cart_data:
            total += i.total_price
        if 'outofstock' in request.session:
            del request.session['outofstock']
            return render(request, 'cart.html', {'cart_data': cart_data, 'login': True, 'total': total,
                                                 'outofstock': "The product is our of stock for a while"})
        else:
            if cart_data:
                return render(request, 'cart.html',
                              {'cart_data': cart_data, 'login': True, 'total': total, 'data': True})
            else:
                return render(request, 'cart.html', {'cart_data': cart_data, 'login': True, 'total': total})
    else:
        return render(request, 'cart.html')


@customer_required
def plus_pro(request, id):
    user_data = User.objects.get(email=request.session['login'])
    cart_pro = Cart.objects.get(id=id, users=user_data, order_id=0)
    pro = Product.objects.get(id=cart_pro.pro.id)
    if pro.stock is not None and pro.stock <= 0:
        request.session['outofstock'] = True
        return redirect('cart_view')
    else:
        cart_pro.qty += 1
        cart_pro.total_price += cart_pro.pro.price
        cart_pro.save()
        if pro.stock is not None:
            pro.stock -= 1
            pro.save()
        return redirect('cart_view')


@customer_required
def minus_pro(request,id):
    user_data = User.objects.get(email=request.session['login'])
    cart_pro = Cart.objects.get(id=id, users=user_data, order_id=0)
    if cart_pro.qty == 1:
        pro = Product.objects.get(id=cart_pro.pro.id)
        if pro.stock is not None:
            pro.stock += cart_pro.qty
            pro.save()
        cart_pro.delete()
        return redirect('cart_view')
    else:
        cart_pro.qty -= 1
        cart_pro.total_price -= cart_pro.pro.price
        cart_pro.save()
        pro = Product.objects.get(id=cart_pro.pro.id)
        if pro.stock is not None:
            pro.stock += 1
            pro.save()
        return redirect('cart_view')


@customer_required
def remove(request, id):
    user_data = User.objects.get(email=request.session['login'])
    cart_data = Cart.objects.get(id=id, users=user_data, order_id=0)
    pro = Product.objects.get(id=cart_data.pro.id)
    if pro.stock is not None:
        pro.stock += cart_data.qty
        pro.save()
    cart_data.delete()
    return redirect('cart_view')


@customer_required
def removeall(request):
   reg=User.objects.get(email=request.session['login'])
   cart=Cart.objects.filter(users=reg, order_id=0)
   for i in cart:
      pro=Product.objects.get(id=i.pro.id)
      if pro.stock is not None:
         pro.stock+=i.qty
         pro.save()
      i.delete()
   return redirect('cart_view')

@customer_required
def checkout(request):
    if 'login' in request.session:
        loggin = User.objects.get(email=request.session['login'])
        checkout_items, total, checkout_source = _get_checkout_items(request, loggin)

        if not checkout_items:
            messages.error(request, 'There is nothing to checkout right now.')
            return redirect('cart_view')

        for item in checkout_items:
            if item.pro.stock is not None and not hasattr(item, 'order_id') and item.qty > item.pro.stock:
                request.session.pop('buy_now_checkout', None)
                request.session.modified = True
                messages.error(request, f'Only {item.pro.stock} item(s) are available for {item.pro.name}.')
                return redirect('product_detail', id=item.pro.id)

        if request.method == 'POST':
            checkout_data = {
                'first_name': request.POST['first_name'],
                'mobile': request.POST['mobile'],
                'address': request.POST['address'],
                'city': request.POST['city'],
                'state': request.POST['state'],
                'pincode': request.POST['pincode'],
            }

            _create_store_orders(loggin, checkout_items, checkout_data, 'COD')
            request.session.pop('buy_now_checkout', None)
            request.session.modified = True
            messages.success(request, 'Order placed successfully.')
            return redirect('index')
        else:
            return render(request, 'checkout.html',
                          {
                              'login': True,
                              'cart_data': checkout_items,
                              'loggin': loggin,
                              'total': total,
                              'checkout_source': checkout_source,
                          })
    else:
        return redirect('login')


def _get_bmi_insights(bmi_value, height_cm=None):
    bmi_value = float(bmi_value or 0)
    if bmi_value < 18.5:
        category = 'Underweight'
        description = 'You are underweight. A balanced meal plan and strength work can help you build healthy weight.'
        color = '#2ecc71'
        tips = [
            'Eat nutrient-dense foods like nuts, dairy, fruits, and whole grains.',
            'Include strength training to support muscle gain.',
            'Add 5-6 smaller meals through the day if large meals feel difficult.',
            'Track progress weekly so your plan stays realistic and sustainable.',
        ]
        indicator_position = (bmi_value / 18.5) * 25 if bmi_value > 0 else 10
    elif bmi_value < 25:
        category = 'Normal Weight'
        description = 'You are in the healthy BMI range. Keep your meals, hydration, sleep, and workouts consistent.'
        color = '#f1c40f'
        tips = [
            'Maintain a balanced diet with protein, fiber, and whole foods.',
            'Aim for regular workouts through the week.',
            'Keep hydration and sleep consistent to support recovery.',
            'Recheck BMI regularly to stay on track.',
        ]
        indicator_position = 25 + ((bmi_value - 18.5) / 6.5) * 25
    elif bmi_value < 30:
        category = 'Overweight'
        description = 'You are above the healthy BMI range. A steady routine with food control and training can help.'
        color = '#e67e22'
        tips = [
            'Reduce sugary drinks and highly processed foods.',
            'Start with walking, cycling, or other repeatable cardio sessions.',
            'Add strength training to preserve muscle while losing fat.',
            'Set small weekly goals instead of chasing fast changes.',
        ]
        indicator_position = 50 + ((bmi_value - 25) / 5) * 25
    else:
        category = 'Obese'
        description = 'You are in the obese range. It is best to work with a doctor or coach on a gradual, safe plan.'
        color = '#e74c3c'
        tips = [
            'Start with low-impact movement and build gradually.',
            'Follow a structured meal routine with portion control.',
            'Track weight, BMI, and habits consistently.',
            'Ask a healthcare professional for personalized guidance if needed.',
        ]
        indicator_position = 75 + min(((bmi_value - 30) / 10) * 25, 25)

    healthy_range = 'Calculate your BMI to see your healthy range.'
    if height_cm:
        height_m = float(height_cm) / 100
        if height_m > 0:
            min_weight = round(18.5 * height_m * height_m, 1)
            max_weight = round(24.9 * height_m * height_m, 1)
            healthy_range = f'{min_weight} kg - {max_weight} kg'

    return {
        'category': category,
        'description': description,
        'color': color,
        'tips': tips,
        'indicator_position': max(0, min(indicator_position, 100)),
        'healthy_range': healthy_range,
    }

@customer_required
def bmi_calculator(request):
    context = {}

    if 'login' in request.session:
        user = User.objects.get(email=request.session['login'])

        if request.method == 'POST':
            unit = request.POST.get('unit', 'metric')

            if unit == 'imperial':
                feet = float(request.POST.get('height_ft', 0) or 0)
                inches = float(request.POST.get('height_in', 0) or 0)
                weight_lbs = float(request.POST.get('weight_lbs', 0) or 0)
                total_inches = (feet * 12) + inches
                height_cm = round(total_inches * 2.54, 2)
                weight = round(weight_lbs / 2.205, 2)
            else:
                height_cm = float(request.POST.get('height_cm', 0) or 0)
                weight = float(request.POST.get('weight_kg', 0) or 0)

            height_m = height_cm / 100
            bmi = round(weight / (height_m * height_m), 2) if height_m > 0 else 0

            FitnessProgress.objects.create(
                customer=user,
                weight=weight,
                height=height_cm,
                bmi=bmi,
                record_date=date.today()
            )
            messages.success(request, 'BMI record saved successfully.')
            return redirect('bmi_calculator')

        progresses = FitnessProgress.objects.filter(customer=user).order_by('-record_date', '-id')[:10]
        latest_progress = progresses.first()
        bmi_insights = _get_bmi_insights(
            latest_progress.bmi if latest_progress else 0,
            latest_progress.height if latest_progress else None,
        )
        context.update({
            'login': True,
            'progresses': progresses,
            'latest_progress': latest_progress,
            'bmi_insights': bmi_insights,
            'selected_gender': (user.gender or 'male').lower(),
        })
    else:
        bmi_insights = _get_bmi_insights(24.2, 170)
        context.update({
            'progresses': [],
            'latest_progress': None,
            'bmi_insights': bmi_insights,
            'selected_gender': 'male',
        })

    return render(request, 'bmi.html', context)

@customer_required
def userprofile(request):
    if 'login' not in request.session:
        messages.error(request, 'Please login first to view your profile.')
        return redirect('login')

    user = User.objects.get(email=request.session['login'])
    membership = _get_active_membership(user)
    latest_progress = FitnessProgress.objects.filter(customer=user).order_by('-record_date', '-id').first()

    if request.method == 'POST':
        user.firstname = request.POST.get('firstname', '').strip()
        user.lastname = request.POST.get('lastname', '').strip()
        new_email = request.POST.get('email', '').strip()

        if not new_email:
            messages.error(request, 'Email is required.')
            return redirect('userprofile')

        if User.objects.filter(email=new_email).exclude(id=user.id).exists():
            messages.error(request, 'This email is already in use by another account.')
            return redirect('userprofile')

        user.email = new_email
        user.mobile = request.POST.get('mobile', '').strip()
        user.address = request.POST.get('address', '').strip()
        user.city = request.POST.get('city', '').strip()
        user.state = request.POST.get('state', '').strip()
        user.gender = request.POST.get('gender', '').strip() or None

        pincode = request.POST.get('pincode', '').strip()
        if pincode:
            try:
                user.pincode = int(pincode)
            except ValueError:
                messages.error(request, 'Pincode must be a number.')
                return redirect('userprofile')

        if request.FILES.get('profile_pic'):
            user.profile_pic = request.FILES['profile_pic']

        user.save()
        request.session['login'] = user.email
        messages.success(request, 'Profile updated successfully.')
        return redirect('userprofile')

    return render(request, 'Userprofile.html', {
        'login': True,
        'profile_user': user,
        'membership': membership,
        'latest_progress': latest_progress,
    })

@admin_required
def dash(request):
    customers = User.objects.filter(role='customer').order_by('-id')
    trainers = Trainer.objects.select_related('users').all()
    packages = Package.objects.all()
    products = Product.objects.select_related('category').all()
    memberships = Membership.objects.select_related('customer', 'package', 'trainer', 'trainer__users').order_by('-start_date', '-id')
    payments = Payment.objects.select_related('customer', 'membership', 'membership__package').order_by('-payment_date')
    notices = Notice.objects.select_related('created_by').order_by('-created_at')[:4]
    orders = Order.objects.select_related('pro', 'users').order_by('-datetime')

    total_revenue = sum(float(item.amount) for item in payments if item.status.lower() == 'paid')
    active_memberships = memberships.filter(status__iexact='active', end_date__gte=date.today()).count()
    low_stock_products = products.filter(stock__lte=10).order_by('stock', 'name')[:5]

    recent_memberships = []
    for membership in memberships[:5]:
        recent_memberships.append({
            'customer_name': f"{membership.customer.firstname} {membership.customer.lastname}".strip() or membership.customer.email,
            'customer_email': membership.customer.email,
            'package_name': membership.package.name,
            'trainer_name': (
                f"{membership.trainer.users.firstname} {membership.trainer.users.lastname}".strip()
                if membership.trainer else 'Self-guided'
            ),
            'start_date': membership.start_date,
            'end_date': membership.end_date,
            'status': membership.status,
        })

    recent_payments = payments[:5]
    recent_orders = orders[:5]

    return render(request, 'dash.html', {
        'customers': customers,
        'trainers': trainers,
        'packages': packages,
        'products': products,
        'customer_count': customers.count(),
        'trainer_count': trainers.count(),
        'package_count': packages.count(),
        'product_count': products.count(),
        'context': date.today(),
        'active_memberships': active_memberships,
        'total_revenue': round(total_revenue, 2),
        'payment_count': payments.count(),
        'order_count': orders.count(),
        'notice_count': notices.count(),
        'recent_memberships': recent_memberships,
        'recent_payments': recent_payments,
        'recent_orders': recent_orders,
        'low_stock_products': low_stock_products,
        'latest_notices': notices,
    })

@admin_required
def adminpackage(request):
    pack=Package.objects.all()
    return render(request, 'addpack.html',{'pack':pack})

@admin_required
def addpackage(request):
    if request.method=='POST':
        pack=Package()
        pack.name=request.POST['name']
        pack.duration_months=request.POST['duration_months']
        pack.price=request.POST['price']
        pack.description=request.POST['description']
        pack.save()
        return render(request,'addpackage.html',{'added':"package added !"})
    else:
        return render(request,'addpackage.html')
     
@admin_required
def update_package(request, id):
    pack = Package.objects.get(id=id)
    if request.method == 'POST':
        pack.name = request.POST['name']
        pack.duration_months = request.POST['duration_months']
        pack.price = request.POST['price']
        pack.description = request.POST['description']
        pack.save()
        return redirect('adminpackage')  
    else:
        return render(request, 'update_package.html', {'pack': pack})

@admin_required
def view_package(request, id):
    pack = Package.objects.get(id=id)
    memberships = Membership.objects.filter(package=pack).select_related('customer', 'trainer', 'trainer__users')
    return render(request, 'view_package.html', {
        'pack': pack,
        'memberships': memberships,
        'member_count': memberships.count(),
    })

@admin_required
def delete_package(request, id):
    pack = Package.objects.get(id=id)
    pack.delete()
    return redirect('adminpackage')
    
@admin_required
def edit_product(request, id):
    product = Product.objects.get(id=id)
    cat=Category.objects.all()
    if request.method == 'POST':
        product.name = request.POST['name']
        product.category = Category.objects.get(id=request.POST['category'])
        product.price = request.POST['price']
        product.desc=request.POST['desc']
        product.stock=request.POST['stock']
        if request.FILES.get('image'):
            product.image = request.FILES['image']
        product.save()
        return redirect('adminproduct')  
    else:
        return render(request, 'edit_product.html', {'product': product,'cat':cat})
    

@admin_required
def admincustomer(request):
    customers = User.objects.filter(role='customer').order_by('id')

    for customer in customers:
        customer.membership = (
            Membership.objects.filter(customer=customer)
            .select_related('package')
            .order_by('-start_date')
            .first()
        )

    return render(request, 'addcustomer.html', {'user': customers})

@admin_required
def delete_customer(request, id):
    customer = User.objects.get(id=id, role='customer')
    customer.delete()
    return redirect('admincustomer')

@admin_required
def admintrainer(request):
    trainers = Trainer.objects.select_related('users').all()
    trainer_rows = []
    for trainer in trainers:
        feedbacks = Feedback.objects.filter(trainer=trainer)
        rating = 0
        if feedbacks.exists():
            rating = round(sum(item.rating for item in feedbacks) / feedbacks.count(), 1)
        trainer_rows.append({
            'id': trainer.id,
            'name': f"{trainer.users.firstname} {trainer.users.lastname}".strip(),
            'email': trainer.users.email,
            'phone': trainer.users.mobile,
            'specialty': trainer.category,
            'experience': trainer.experience_year,
            'student_count': Membership.objects.filter(trainer=trainer).count(),
            'rating': rating,
            'is_active': True,
        })
    return render(request, 'admintrainer.html', {
        'trainers': trainer_rows,
        'active_trainers': len(trainer_rows),
        'gym_trainers': len([t for t in trainer_rows if t['specialty'] == 'gym']),
        'yoga_trainers': len([t for t in trainer_rows if t['specialty'] == 'yoga']),
        'zumba_trainers': len([t for t in trainer_rows if t['specialty'] == 'zumba']),
    })

@admin_required
def adminprofile(request):
    return render(request, 'adminprofile.html')

@admin_required
def adminproduct(request):
    categories = Category.objects.all().order_by('name')
    products = Product.objects.select_related('category').all().order_by('-id')
    category_rows = []

    for category in categories:
        category_rows.append({
            'id': category.id,
            'name': category.name,
            'image': category.image,
            'product_count': Product.objects.filter(category=category).count(),
        })

    return render(request, 'addproducts.html', {
        'product': products,
        'cat': categories,
        'category_rows': category_rows,
    })

@admin_required
def admin_feedback(request):
    feedback_list = Feedback.objects.select_related('customer', 'trainer', 'trainer__users').order_by('-created_at')
    average_rating = 0
    if feedback_list:
        average_rating = round(sum(item.rating for item in feedback_list) / feedback_list.count(), 1)

    return render(
        request,
        'admin_feedback.html',
        {
            'feedback_list': feedback_list,
            'feedback_count': feedback_list.count(),
            'average_rating': average_rating,
            'today': date.today(),
        }
    )

@admin_required
def admin_payments(request):
    payments = Payment.objects.select_related('customer', 'membership', 'membership__package').order_by('-payment_date')
    total_amount = sum(float(item.amount) for item in payments)
    return render(request, 'admin_payments.html', {
        'payments': payments,
        'payment_count': payments.count(),
        'total_amount': total_amount,
        'today': date.today(),
    })

@admin_required
def admin_invoices(request):
    invoices = Invoice.objects.select_related('payment', 'payment__customer').order_by('-generated_date')
    return render(request, 'admin_invoices.html', {
        'invoices': invoices,
        'invoice_count': invoices.count(),
        'today': date.today(),
    })

@admin_required
def admin_notices(request):
    notices = Notice.objects.select_related('created_by', 'recipient').order_by('-created_at')
    edit_notice = None
    customers = User.objects.filter(role='customer').order_by('firstname', 'email')
    trainers = User.objects.filter(role='trainer').order_by('firstname', 'email')

    edit_notice_id = request.GET.get('edit')
    if edit_notice_id:
        edit_notice = Notice.objects.filter(id=edit_notice_id).first()

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        message = request.POST.get('message', '').strip()
        notice_id = request.POST.get('notice_id')
        audience = request.POST.get('audience', 'all')
        recipient_id = request.POST.get('recipient_id', '').strip()
        send_email_flag = request.POST.get('send_email') == 'on'
        recipient = User.objects.filter(id=recipient_id).first() if recipient_id else None

        if audience in ['specific_customer', 'specific_trainer'] and recipient is None:
            return render(request, 'admin_notices.html', {
                'notices': notices,
                'today': date.today(),
                'edit_notice': edit_notice,
                'customers': customers,
                'trainers': trainers,
                'saved': 'Please choose a specific recipient for this notification.',
            })

        if notice_id:
            notice = Notice.objects.filter(id=notice_id).first()
            if notice:
                notice.title = title
                notice.message = message
                notice.audience = audience
                notice.recipient = recipient
                notice.send_email = send_email_flag
                notice.save()
                email_message = None
                if send_email_flag:
                    _, email_message = _send_notice_email(notice)
                return render(request, 'admin_notices.html', {
                    'notices': Notice.objects.select_related('created_by', 'recipient').order_by('-created_at'),
                    'today': date.today(),
                    'customers': customers,
                    'trainers': trainers,
                    'saved': email_message or f'Notice "{notice.title}" updated successfully.',
                })
        else:
            created_by = User.objects.filter(id=request.session.get('user_id')).first()
            notice = Notice.objects.create(
                title=title,
                message=message,
                audience=audience,
                recipient=recipient,
                send_email=send_email_flag,
                created_by=created_by
            )
            email_message = None
            if send_email_flag:
                _, email_message = _send_notice_email(notice)
            return render(request, 'admin_notices.html', {
                'notices': Notice.objects.select_related('created_by', 'recipient').order_by('-created_at'),
                'today': date.today(),
                'customers': customers,
                'trainers': trainers,
                'saved': email_message or f'Notice "{notice.title}" created successfully.',
            })

    return render(request, 'admin_notices.html', {
        'notices': notices,
        'today': date.today(),
        'edit_notice': edit_notice,
        'customers': customers,
        'trainers': trainers,
    })


@admin_required
def delete_notice(request, id):
    Notice.objects.filter(id=id).delete()
    return redirect('admin_notices')

@admin_required
def del_product(request, id):
    Product.objects.get(id=id).delete()
    return redirect('adminproduct')

@admin_required
def add_product(request):
    categories = Category.objects.all().order_by('name')

    if request.method == 'POST':
        category_id = request.POST.get('category')
        category = Category.objects.filter(id=category_id).first()

        Product.objects.create(
            name=request.POST['name'],
            category=category,
            stock=request.POST['stock'],
            price=request.POST['price'],
            desc=request.POST['description'],
            image=request.FILES.get('image'),
        )
        messages.success(request, 'Product added successfully.')
        return redirect('adminproduct')

    return render(request, 'add_product.html', {'cat': categories})

@admin_required
def add_category(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()

        if not name:
            messages.error(request, 'Category name is required.')
            return redirect('adminproduct')

        if Category.objects.filter(name__iexact=name).exists():
            messages.error(request, 'Category already exists.')
            return redirect('adminproduct')

        Category.objects.create(
            name=name,
            image=request.FILES.get('image') or '',
        )
        messages.success(request, 'Category added successfully.')
    return redirect('adminproduct')

@admin_required
def edit_category(request, id):
    category = Category.objects.get(id=id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()

        if not name:
            messages.error(request, 'Category name is required.')
            return redirect('adminproduct')

        if Category.objects.filter(name__iexact=name).exclude(id=category.id).exists():
            messages.error(request, 'Another category with this name already exists.')
            return redirect('adminproduct')

        category.name = name
        if request.FILES.get('image'):
            category.image = request.FILES['image']
        category.save()
        messages.success(request, 'Category updated successfully.')

    return redirect('adminproduct')

@admin_required
def delete_category(request, id):
    category = Category.objects.get(id=id)
    product_count = Product.objects.filter(category=category).count()

    if product_count:
        messages.error(
            request,
            f'Cannot delete "{category.name}" because {product_count} product(s) still use this category.'
        )
    else:
        category.delete()
        messages.success(request, 'Category deleted successfully.')

    return redirect('adminproduct')


@admin_required
def orderdisplay(request):
    orders=Order.objects.all()
    return render(request,'order.html',{'orders':orders})

@customer_required
def user_orders(request):
    if 'login' not in request.session:
        messages.error(request, 'Please login first to view your orders.')
        return redirect('login')

    user = User.objects.get(email=request.session['login'])
    orders = list(Order.objects.filter(users=user).select_related('pro').order_by('-datetime', '-id'))
    recent_orders = orders[:5]
    old_orders = orders[5:]

    total_spent = sum(order.total_price for order in orders)
    total_items = sum(order.qty for order in orders)

    return render(request, 'user_orders.html', {
        'login': True,
        'orders': orders,
        'recent_orders': recent_orders,
        'old_orders': old_orders,
        'total_spent': total_spent,
        'total_items': total_items,
    })

@customer_required
def myplan(request):
    if 'login' not in request.session:
        return redirect('login')

    user = User.objects.get(email=request.session['login'])
    membership = _get_active_membership(user)
    if membership is None:
        messages.info(request, 'Purchase a membership first to unlock your plan, trainer guidance, and progress tracking.')
        return redirect('usermember')

    diet_plans = DietPlan.objects.filter(customer=user).select_related('trainer', 'trainer__users').order_by('-created_at')
    exercise_plans = ExercisePlan.objects.filter(customer=user).select_related('trainer', 'trainer__users').order_by('-id')
    progresses = FitnessProgress.objects.filter(customer=user).order_by('-record_date')
    payments = Payment.objects.filter(customer=user).select_related('membership', 'membership__package').order_by('-payment_date')
    invoices = Invoice.objects.filter(payment__customer=user).select_related('payment').order_by('-generated_date')
    notices = _get_visible_notices_for_user(user, role='customer')[:5]
    feedbacks = Feedback.objects.filter(customer=user).select_related('trainer', 'trainer__users').order_by('-created_at')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'feedback' and membership and membership.trainer:
            Feedback.objects.create(
                customer=user,
                trainer=membership.trainer,
                rating=request.POST['rating'],
                comments=request.POST['comments']
            )
        return redirect('myplan')

    return render(request,'myplan.html', {
        'login': True,
        'membership': membership,
        'diet_plans': diet_plans,
        'exercise_plans': exercise_plans,
        'progresses': progresses,
        'payments': payments,
        'invoices': invoices,
        'notices': notices,
        'feedbacks': feedbacks,
    })

@customer_required
def trainer_detail(request):
    if 'login' not in request.session:
        return redirect('login')

    user = User.objects.get(email=request.session['login'])
    membership = _get_active_membership(user)
    if membership is None:
        messages.info(request, 'Purchase a membership first to view your trainer details and assigned plans.')
        return redirect('usermember')

    assigned_trainer = membership.trainer
    diet_plans = DietPlan.objects.filter(customer=user).select_related('trainer', 'trainer__users').order_by('-created_at')
    exercise_plans = ExercisePlan.objects.filter(customer=user).select_related('trainer', 'trainer__users').order_by('-id')
    trainer_feedbacks = Feedback.objects.filter(trainer=assigned_trainer).select_related('customer').order_by('-created_at')[:5] if assigned_trainer else []

    average_rating = 0
    feedback_count = 0
    if assigned_trainer:
        feedback_queryset = Feedback.objects.filter(trainer=assigned_trainer)
        feedback_count = feedback_queryset.count()
        if feedback_count:
            average_rating = round(sum(item.rating for item in feedback_queryset) / feedback_count, 1)

    return render(request, 'trainer_detail.html', {
        'login': True,
        'membership': membership,
        'assigned_trainer': assigned_trainer,
        'diet_plans': diet_plans,
        'exercise_plans': exercise_plans,
        'trainer_feedbacks': trainer_feedbacks,
        'average_rating': average_rating,
        'feedback_count': feedback_count,
    })

def usermember(request):
    if 'login' not in request.session:
        return redirect('login')

    user = User.objects.get(email=request.session['login'])
    active_membership = _get_active_membership(user)
    packages = Package.objects.all()
    trainers = Trainer.objects.select_related('users').all()

    if request.method == 'POST':
        if active_membership:
            messages.error(
                request,
                f'Your current membership stays active until {active_membership.end_date:%d %b %Y}. You can book a new plan after it ends.'
            )
            return redirect('usermember')

        package_id = request.POST.get('package_id')
        trainer_id = request.POST.get('trainer_id')

        if not package_id:
            messages.error(request, 'Please select a package first.')
            return redirect('usermember')

        package = Package.objects.filter(id=package_id).first()
        if package is None:
            messages.error(request, 'Selected package was not found.')
            return redirect('usermember')

        trainer = Trainer.objects.filter(id=trainer_id).first() if trainer_id and trainer_id != '0' else None

        _create_membership_records(
            user=user,
            package=package,
            trainer=trainer,
            payment_method='Cash on Delivery',
            payment_status='Pending',
        )
        messages.success(request, 'Membership booked successfully. You can now view it in My Plan.')
        return redirect('myplan')

    trainer_cards = []
    for trainer in trainers:
        feedbacks = Feedback.objects.filter(trainer=trainer)
        rating = 0
        if feedbacks.exists():
            rating = round(sum(item.rating for item in feedbacks) / feedbacks.count(), 1)
        trainer_cards.append({
            'id': trainer.id,
            'name': f"{trainer.users.firstname} {trainer.users.lastname}".strip(),
            'specialty': trainer.category,
            'experience': trainer.experience_year,
            'rating': rating,
        })

    return render(request,'membership.html', {
        'packages': packages,
        'trainers': trainer_cards,
        'active_membership': active_membership,
    })

@trainer_required
def trainerdash(request):
    trainer = _get_logged_trainer(request)
    memberships = _get_trainer_memberships(trainer)
    diet_count = DietPlan.objects.filter(trainer=trainer).count()
    exercise_count = ExercisePlan.objects.filter(trainer=trainer).count()
    feedbacks = Feedback.objects.filter(trainer=trainer)
    recent_diet_plans = DietPlan.objects.filter(trainer=trainer).select_related('customer').order_by('-created_at')[:4]
    recent_exercise_plans = ExercisePlan.objects.filter(trainer=trainer).select_related('customer').order_by('-id')[:4]
    notices = _get_visible_notices_for_user(trainer.users, role='trainer')[:5]

    rating_count = feedbacks.count()
    average_rating = 0
    if rating_count:
        average_rating = round(sum(i.rating for i in feedbacks) / rating_count, 1)

    return render(
        request,
        'trainerdash.html',
        {
            'trainer_data': trainer,
            'memberships': memberships,
            'customer_count': memberships.count(),
            'diet_count': diet_count,
            'exercise_count': exercise_count,
            'average_rating': average_rating,
            'rating_count': rating_count,
            'today': date.today(),
            'recent_diet_plans': recent_diet_plans,
            'recent_exercise_plans': recent_exercise_plans,
            'notices': notices,
        }
    )

@trainer_required
def trainer_customers(request):
    trainer = _get_logged_trainer(request)
    memberships = _get_trainer_memberships(trainer)
    return render(request, 'trainer_customers.html', {
        'trainer_data': trainer,
        'memberships': memberships,
        'customer_count': memberships.count(),
    })


@trainer_required
def trainer_progress(request):
    trainer = _get_logged_trainer(request)
    memberships = _get_trainer_memberships(trainer)
    customer_ids = list(memberships.values_list('customer_id', flat=True))
    progresses = FitnessProgress.objects.filter(customer_id__in=customer_ids).select_related('customer').order_by('-record_date', '-id')
    latest_progress = {}

    for progress in progresses:
        if progress.customer_id not in latest_progress:
            latest_progress[progress.customer_id] = progress

    customer_progress_cards = []
    for membership in memberships:
        customer_progress_cards.append({
            'customer_name': f"{membership.customer.firstname} {membership.customer.lastname}".strip(),
            'package_name': membership.package.name,
            'latest': latest_progress.get(membership.customer_id),
        })

    return render(request, 'trainer_progress.html', {
        'trainer_data': trainer,
        'memberships': memberships,
        'progresses': progresses,
        'customer_progress_cards': customer_progress_cards,
    })


@trainer_required
def trainer_profile(request):
    trainer = _get_logged_trainer(request)

    if request.method == 'POST':
        trainer.users.firstname = request.POST.get('firstname', '')
        trainer.users.lastname = request.POST.get('lastname', '')
        trainer.users.email = request.POST.get('email', '')
        trainer.users.mobile = request.POST.get('mobile', '')
        trainer.users.address = request.POST.get('address', '')
        trainer.users.city = request.POST.get('city', '')
        trainer.users.state = request.POST.get('state', '')
        trainer.users.pincode = request.POST.get('pincode', 0)
        trainer.users.save()

        trainer.category = request.POST.get('category', trainer.category)
        trainer.experience_year = request.POST.get('experience_year', trainer.experience_year)
        trainer.specialization = request.POST.get('specialization', trainer.specialization)
        trainer.qualification = request.POST.get('qualification', trainer.qualification)
        trainer.save()

        messages.success(request, 'Trainer profile updated successfully.')
        return redirect('trainer_profile')

    return render(request, 'trainer_profile.html', {'trainer_data': trainer})


@trainer_required
def trainer_assign_diet(request):
    trainer = _get_logged_trainer(request)
    memberships = _get_trainer_memberships(trainer)
    diet_plans = DietPlan.objects.filter(trainer=trainer).select_related('customer').order_by('-created_at')

    if request.method == 'POST':
        customer = _get_assigned_customer(trainer, request.POST['customer_id'])
        if customer is None:
            messages.error(request, 'You can only assign diet plans to customers linked to your memberships.')
            return redirect('trainer_assign_diet')
        DietPlan.objects.create(
            trainer=trainer,
            customer=customer,
            diet_description=request.POST['diet_description'],
            calories=request.POST['calories']
        )
        return redirect('trainer_assign_diet')

    return render(request, 'trainer_assign_diet.html', {
        'trainer_data': trainer,
        'memberships': memberships,
        'diet_plans': diet_plans,
    })

@trainer_required
def edit_diet_plan(request, id):
    trainer = _get_logged_trainer(request)
    diet_plan = DietPlan.objects.select_related('customer').get(id=id, trainer=trainer)
    memberships = _get_trainer_memberships(trainer)

    if request.method == 'POST':
        customer = _get_assigned_customer(trainer, request.POST['customer_id'])
        if customer is None:
            messages.error(request, 'You can only assign diet plans to customers linked to your memberships.')
            return redirect('edit_diet_plan', id=id)
        diet_plan.customer = customer
        diet_plan.diet_description = request.POST['diet_description']
        diet_plan.calories = request.POST['calories']
        diet_plan.save()
        messages.success(request, 'Diet plan updated successfully.')
        return redirect('trainer_assign_diet')

    return render(request, 'edit_diet_plan.html', {
        'trainer_data': trainer,
        'diet_plan': diet_plan,
        'memberships': memberships,
    })


@trainer_required
def delete_diet_plan(request, id):
    trainer = _get_logged_trainer(request)
    DietPlan.objects.get(id=id, trainer=trainer).delete()
    messages.success(request, 'Diet plan deleted successfully.')
    return redirect('trainer_assign_diet')


@trainer_required
def trainer_assign_exercise(request):
    trainer = _get_logged_trainer(request)
    memberships = _get_trainer_memberships(trainer)
    exercise_plans = ExercisePlan.objects.filter(trainer=trainer).select_related('customer').order_by('-id')

    if request.method == 'POST':
        customer = _get_assigned_customer(trainer, request.POST['customer_id'])
        if customer is None:
            messages.error(request, 'You can only assign exercise plans to customers linked to your memberships.')
            return redirect('trainer_assign_exercise')
        ExercisePlan.objects.create(
            trainer=trainer,
            customer=customer,
            exercise_name=request.POST['exercise_name'],
            sets=request.POST['sets'],
            reps=request.POST['reps'],
            instructions=request.POST['instructions']
        )
        return redirect('trainer_assign_exercise')

    return render(request, 'trainer_assign_exercise.html', {
        'trainer_data': trainer,
        'memberships': memberships,
        'exercise_plans': exercise_plans,
    })


@trainer_required
def edit_exercise_plan(request, id):
    trainer = _get_logged_trainer(request)
    exercise_plan = ExercisePlan.objects.select_related('customer').get(id=id, trainer=trainer)
    memberships = _get_trainer_memberships(trainer)

    if request.method == 'POST':
        customer = _get_assigned_customer(trainer, request.POST['customer_id'])
        if customer is None:
            messages.error(request, 'You can only assign exercise plans to customers linked to your memberships.')
            return redirect('edit_exercise_plan', id=id)
        exercise_plan.customer = customer
        exercise_plan.exercise_name = request.POST['exercise_name']
        exercise_plan.sets = request.POST['sets']
        exercise_plan.reps = request.POST['reps']
        exercise_plan.instructions = request.POST['instructions']
        exercise_plan.save()
        messages.success(request, 'Exercise plan updated successfully.')
        return redirect('trainer_assign_exercise')

    return render(request, 'edit_exercise_plan.html', {
        'trainer_data': trainer,
        'exercise_plan': exercise_plan,
        'memberships': memberships,
    })


@trainer_required
def delete_exercise_plan(request, id):
    trainer = _get_logged_trainer(request)
    ExercisePlan.objects.get(id=id, trainer=trainer).delete()
    messages.success(request, 'Exercise plan deleted successfully.')
    return redirect('trainer_assign_exercise')

from rest_framework.response import Response
from rest_framework.decorators import api_view
from .serialize_ import user_serialize

@api_view(['GET'])
def api_user(request,id):
   register_user = User.objects.filter(id=id).first()
   if register_user is None:
      return Response({'detail': 'User not found.'}, status=404)
   # serialized_user = user_serialize(register_user,many=True)
   serialized_user = user_serialize(register_user)
   return Response(serialized_user.data)

@api_view(['PATCH'])
def update_data(request,id):
   old_data=User.objects.filter(id=id).first()
   if old_data is None:
      return Response({'detail': 'User not found.'}, status=404)
   serialized_user=user_serialize(old_data,data=request.data,partial=True)
   if serialized_user.is_valid():
      serialized_user.save()
      return Response("data Updated")
   else:
      return Response("failed to update")
   
@api_view(['DELETE']) 
def delete_data(request,id):
   reg=User.objects.filter(id=id).first()
   if reg is None:
      return Response({'detail': 'User not found.'}, status=404)
   reg.delete()
   return Response("Data Deleted")

@api_view(['POST'])
def api_store_data(request):
   serialized_user=user_serialize(data=request.data)
   if serialized_user.is_valid():
      serialized_user.save()
      return Response("data stored")
   else:
    return Response("failed to store")
