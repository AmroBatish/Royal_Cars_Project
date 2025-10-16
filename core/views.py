from django.shortcuts import render, redirect, get_object_or_404 , HttpResponseRedirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.core.mail import send_mail
from django.conf import settings
import stripe
from .models import Booking, Car, Contract, Review
from django.db.models import Avg, Count, Sum

from django.utils import timezone
from datetime import datetime




User = get_user_model()


# ===========================
# PUBLIC PAGES
# ===========================
def index(request):
    owners = User.objects.filter(role="owner", is_approved=True)
    cars = Car.objects.filter(is_available=True)
    return render(request, "index.html", {"owners": owners, "cars": cars})


def about(request):
    return render(request, "about.html")


def service(request):
    return render(request, "service.html")


def team(request):
    return render(request, "team.html")


def testimonial(request):
    return render(request, "testimonial.html")


def car(request):
    today = timezone.now().date()
    cars = Car.objects.all()
    for c in cars:
        booking = c.bookings.filter(
            return_date__gte=today
        ).order_by("pickup_date").first()
        c.unavailable_booking = booking
    return render(request, "car.html", {"cars": cars})


def car_partial(request):
    sort = request.GET.get("sort")
    cars = Car.objects.all()

    if sort == "popular":
        cars = cars.annotate(num_bookings=Count("bookings")).order_by("-num_bookings")
    elif sort == "rating":
        cars = cars.annotate(avg_rating=Avg("bookings__review__rating")).order_by("-avg_rating")
    elif sort == "price_low":
        cars = cars.order_by("price")
    elif sort == "price_high":
        cars = cars.order_by("-price")
    elif sort == "manual":
        cars = cars.filter(transmission="MANUAL")
    elif sort == "auto":
        cars = cars.filter(transmission="AUTO")
    elif sort == "economic":
        cars = cars.filter(price__lte=50)

    today = timezone.now().date()
    for car in cars:
        car.unavailable_booking = car.bookings.filter(
            return_date__gte=today
        ).order_by("pickup_date").first()

    return render(request, "car_partial.html", {"cars": cars})



def detail(request, pk):
    car = get_object_or_404(Car, pk=pk)

    # نجيب كل التقييمات المرتبطة بالحجوزات لهذه السيارة
    reviews = Review.objects.filter(booking__car=car).select_related("user", "booking")

    # ملخص التقييمات
    avg_rating = reviews.aggregate(Avg("rating"))["rating__avg"]
    total_reviews = reviews.count()

    return render(request, "detail.html", {
        "car": car,
        "reviews": reviews,
        "avg_rating": avg_rating,
        "total_reviews": total_reviews,
    })


def payment_success(request):
    messages.success(request, " Payment completed successfully!")
    return redirect("profile")

def payment_cancel(request):
    messages.warning(request, " Payment canceled.")
    return redirect("profile")
# ===========================
# AUTHENTICATION
# ===========================
def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if not user:
            messages.error(request, " Invalid username or password.")
            return redirect("login")

        # Owners must be approved before login
        if user.role == "owner" and not user.is_approved:
            messages.error(request, " Your account is pending admin approval.")
            return redirect("login")

        
        login(request, user)
        # messages.success(request, f" Welcome back, {user.username}!")
        return render(request, "login.html", {"trigger_verification": True})

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    messages.info(request, " Logged out successfully")
    return redirect("login")


def register_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        phone = request.POST.get("phone", "")
        password = request.POST.get("password")
        confirm = request.POST.get("confirm_password")
        license_image = request.FILES.get("license_image")  # 👈 ناخد صورة الرخصة من الفورم

        # التحقق من كلمة المرور
        if password != confirm:
            messages.error(request, " Passwords do not match.")
            return redirect("register")

        # التحقق من اسم المستخدم
        if User.objects.filter(username=username).exists():
            messages.error(request, " Username already exists.")
            return redirect("register")

        # إنشاء المستخدم العادي (role=user افتراضي)
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            phone=phone,
            license_image=license_image  # 👈 نحفظ الصورة
        )

        # تسجيل الدخول مباشرة
        login(request, user)
        messages.success(request, " Account created successfully.")
        return redirect("index")

    return render(request, "register.html")

def register_owner_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        company_name = request.POST.get("company_name", "")
        phone = request.POST.get("phone", "")
        password = request.POST.get("password")
        confirm = request.POST.get("confirm_password")

        # Check password match
        if password != confirm:
            messages.error(request, " Passwords do not match.")
            return redirect("register_owner")

        # Check username uniqueness
        if User.objects.filter(username=username).exists():
            messages.error(request, " Username already exists.")
            return redirect("register_owner")

        # Create owner account (pending approval)
        User.objects.create_user(
            username=username,
            email=email,
            password=password,
            phone=phone,
            company_name=company_name,
            role="owner",
            is_approved=False,
        )

        messages.info(request, " Account created. Wait for admin approval before login.")
        return redirect("login")

    return render(request, "register_owner.html")


# ===========================
# PROFILE & DASHBOARD
# ===========================
@login_required(login_url="login")
def profile_view(request):
    user = request.user

    # آخر 5 حجوزات للمستخدم
    recent_bookings = Booking.objects.filter(user=user).order_by('-created_at')[:5]

    # آخر 5 عقود مرتبطة بالمستخدم (عن طريق الحجوزات)
    recent_contracts = Contract.objects.filter(booking__user=user).order_by('-created_at')[:5]

    # إحصائيات عامة
    contracts = Contract.objects.filter(booking__user=user)
    total_bookings = contracts.count()
    total_paid = sum(c.total_price for c in contracts)


    return render(request, "profile.html", {
    "user": user,
    "recent_bookings": recent_bookings,
    "recent_contracts": recent_contracts,
    "total_bookings": total_bookings,
    "total_paid": total_paid,
})




@login_required(login_url="login")
def owner_dashboard(request):
    if request.user.role != "owner":
        return redirect("index")

    # آخر 5 سيارات للمالك
    cars = request.user.cars.all()[:5]

    # آخر 5 حجوزات
    bookings = Booking.objects.filter(car__owner=request.user)[:5]

    # التقييمات الخاصة بسيارات المالك
    reviews = Review.objects.filter(
        booking__car__owner=request.user
    ).select_related("booking__car", "user")

    # ملخص لكل سيارة (متوسط وعدد التقييمات)
    cars_with_stats = cars.annotate(
        avg_rating=Avg("bookings__review__rating"),
        total_reviews=Count("bookings__review")
    )

    # آخر 5 تعليقات
    recent_reviews = reviews.order_by("-created_at")[:5]

    # =========================
    # إحصائيات سريعة للـ Dashboard
    # =========================
    all_bookings = Booking.objects.filter(car__owner=request.user)
    total_cars = request.user.cars.count()
    total_bookings = all_bookings.count()
    paid = all_bookings.filter(status=Booking.STATUS_PAID).count()

    # عدد المستخدمين الفريدين
    unique_customers = all_bookings.values("user").distinct().count()

    # إجمالي الدفعات (محسوبة في بايثون باستخدام property total_price)
    contracts = Contract.objects.filter(
        booking__car__owner=request.user,
        booking__status=Booking.STATUS_PAID
    )
    total_payments = sum(c.total_price for c in contracts)

    # =========================
    # Top Customers & Top Cars
    # =========================
    top_customers = (
        Booking.objects.filter(car__owner=request.user, status__in=[Booking.STATUS_APPROVED, Booking.STATUS_PAID])
        .values("user__id", "user__username", "user__email")
        .annotate(total_bookings=Count("id"))
        .order_by("-total_bookings")[:5]
    )

    top_cars = (
        Booking.objects.filter(car__owner=request.user, status__in=[Booking.STATUS_APPROVED, Booking.STATUS_PAID])
        .values("car__id", "car__name")
        .annotate(total_bookings=Count("id"))
        .order_by("-total_bookings")[:5]
    )

    return render(request, "owner_dashboard.html", {
        "cars": cars,
        "bookings": bookings,
        "cars_with_stats": cars_with_stats,
        "recent_reviews": recent_reviews,
        "total_cars": total_cars,
        "total_bookings": total_bookings,
        "paid": paid,
        "unique_customers": unique_customers,
        "total_payments": total_payments,
        "top_customers": top_customers,
        "top_cars": top_cars,
    })


@login_required(login_url="login")
def add_car(request):
    if request.user.role != "owner":
        return redirect("index")

    if request.method == "POST":
        Car.objects.create(
            owner=request.user,
            name=request.POST.get("name"),
            year=request.POST.get("year"),
            transmission=request.POST.get("transmission"),
            mileage=request.POST.get("mileage"),
            price=request.POST.get("price"),
            description=request.POST.get("description", ""),
            image=request.FILES.get("image"),
        )
        messages.success(request, " Car added successfully.")
        return redirect("owner_dashboard")

    return redirect("owner_dashboard")


# ===========================
# BOOKINGS
# ===========================


@login_required(login_url="login")
def booking_view(request):
    if getattr(request.user, "role", None) == "owner":
        return JsonResponse({"status": "error", "message": "Owners cannot create bookings."}, status=403)

    if request.method == "POST" and request.headers.get("x-requested-with") == "XMLHttpRequest":
        car = get_object_or_404(Car, pk=request.POST.get("car"))

        # تحقق من الحقول المطلوبة
        required_fields = ["trip_location", "pickup_date", "pickup_time", "return_date", "return_time"]
        for field in required_fields:
            if not request.POST.get(field):
                return JsonResponse({"status": "error", "message": f"Missing field: {field}"}, status=400)

        pickup_date = datetime.datetime.strptime(request.POST.get("pickup_date"), "%Y-%m-%d").date()
        pickup_time = datetime.datetime.strptime(request.POST.get("pickup_time"), "%H:%M").time()
        return_date = datetime.datetime.strptime(request.POST.get("return_date"), "%Y-%m-%d").date()
        return_time = datetime.datetime.strptime(request.POST.get("return_time"), "%H:%M").time()


        # حقل trip_location يحتوي النص "Pickup → Drop (distance km)"
        trip_location_text = request.POST.get("trip_location")
        try:
            # استخراج المسافة إذا موجودة بين الأقواس
            if "(" in trip_location_text and ")" in trip_location_text:
                distance_text = trip_location_text.split("(")[1].replace("km)", "").strip()
                distance_km = float(distance_text)
            else:
                distance_km = None
        except:
            distance_km = None

        # حفظ الـ pickup و drop كنص (قبل وبعد السهم)
        try:
            pickup_location = trip_location_text.split("→")[0].strip()
            drop_location = trip_location_text.split("→")[1].split("(")[0].strip()
        except:
            pickup_location = trip_location_text
            drop_location = ""

        # استلام الإحداثيات من الفورم
        pickup_lat = request.POST.get("pickup_lat")
        pickup_lng = request.POST.get("pickup_lng")
        dropoff_lat = request.POST.get("dropoff_lat")
        dropoff_lng = request.POST.get("dropoff_lng")

        # ✅ تحقق من وجود حجز متداخل (بالتاريخ)
        overlap = Booking.objects.filter(
            car=car,
            return_date__gte=pickup_date,
            pickup_date__lte=return_date,
        )

        # لو نفس اليوم → تحقق بالوقت كمان
        if pickup_date == return_date:
            overlap = overlap.filter(
                pickup_time__lt=return_time,
                return_time__gt=pickup_time,
            )

        if overlap.exists():
            return JsonResponse({
                "status": "error",
                "message": " This car is already booked in the selected period."
            }, status=400)

        # إنشاء الحجز
        Booking.objects.create(
            user=request.user,
            car=car,
            trip_location=trip_location_text,
            pickup_lat=pickup_lat if pickup_lat else None,
            pickup_lng=pickup_lng if pickup_lng else None,
            dropoff_lat=dropoff_lat if dropoff_lat else None,
            dropoff_lng=dropoff_lng if dropoff_lng else None,
            distance_km=distance_km,
            pickup_date=pickup_date,
            pickup_time=pickup_time,
            return_date=return_date,
            return_time=return_time,
            special_request=request.POST.get("special_request", ""),
        )

        return JsonResponse({"status": "success", "message": " Booking successful! Please wait for confirmation."})

    return JsonResponse({"status": "error", "message": "Invalid request."}, status=400)

@login_required(login_url="login")
def approve_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, car__owner=request.user)
    booking.status = "approved"
    booking.save()

    send_mail(
        " Booking Approved",
        f"Hello {booking.user.username}, your booking for {booking.car.name} has been approved.",
        "noreply@royalcars.com",
        [booking.user.email],
        fail_silently=True,
    )

    messages.success(request, " Booking approved and email sent.")
    return redirect("owner_dashboard")


@login_required(login_url="login")
def reject_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, car__owner=request.user)
    booking.status = "rejected"
    booking.save()

    send_mail(
        " Booking Rejected",
        f"Hello {booking.user.username}, your booking for {booking.car.name} has been rejected.",
        "noreply@royalcars.com",
        [booking.user.email],
        fail_silently=True,
    )

    messages.info(request, " Booking rejected.")
    return redirect("owner_dashboard")

@login_required(login_url="login")
def my_bookings(request):
    bookings = Booking.objects.filter(user=request.user).select_related("car", "contract")
    awaiting_contract = bookings.filter(status="awaiting_contract").first()

    # نحسب التوتال المدفوع
    paid_bookings = bookings.filter(status="paid")
    total_paid = sum(
        (b.rental_days or 1) * float(b.car.price)
        for b in paid_bookings
        if b.car and b.car.price
    )

    return render(request, "my_bookings.html", {
        "bookings": bookings,
        "awaiting_contract": awaiting_contract,
        "total_paid": total_paid,
    })

@login_required(login_url="login")
def pay_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if booking.status != "approved":
        messages.warning(request, " You can only pay after the owner approves your booking.")
        return redirect("my_bookings")
    # مبلغ الدفع (سعر اليوم الواحد) بالسنت
    rental_days = booking.rental_days or 1  # لو الفرق صفر نخليه يوم واحد
    total_amount_cents = int(float(booking.car.price) * rental_days * 100)

    # جلسة Stripe Checkout
    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
    {
        "price_data": {
            "currency": "usd",
            "product_data": {
                "name": f"{booking.car.name} ({rental_days} days)",
                "description": f"Trip: {booking.trip_location}",
                "images": [
                    request.build_absolute_uri(booking.car.image.url)
                      ] if booking.car.image else [],
            },
            "unit_amount": total_amount_cents,  # السعر الكلي
        },
        "quantity": 1,
    }
],
        metadata={"booking_id": str(booking.id), "user_id": str(request.user.id)},
        success_url=f"{settings.DOMAIN}/payment/success/?session_id={{CHECKOUT_SESSION_ID}}&booking={booking.id}",
        cancel_url=f"{settings.DOMAIN}/payment/cancel/?booking={booking.id}",
    )

    return HttpResponseRedirect(session.url)


@login_required(login_url="login")
def payment_success(request):
    booking_id = request.GET.get("booking")
    if not booking_id:
        messages.error(request, " Invalid payment confirmation.")
        return redirect("my_bookings")

    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    # لا نغيّر إلى "paid" الآن
    booking.status = "awaiting_contract"
    booking.save(update_fields=["status"])

    # إنشاء العقد لو غير موجود
    Contract.objects.get_or_create(booking=booking)

    messages.success(request, " Payment successful! Please review and approve your contract.")
    return redirect("my_bookings")



@login_required(login_url="login")
def payment_cancel(request):
    messages.info(request, " Payment canceled.")
    return redirect("profile")



stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", None)


@login_required(login_url="login")
@csrf_exempt
def create_checkout_session(request):
    if request.method == "POST":
        try:
            car = get_object_or_404(Car, pk=request.POST.get("car"))

            # إنشاء حجز مؤقت
            booking = Booking.objects.create(
                user=request.user,
                car=car,
                trip_location=request.POST.get("trip_location"),
                pickup_date=request.POST.get("pickup_date"),
                pickup_time=request.POST.get("pickup_time"),
                special_request=request.POST.get("special_request", ""),
            )

            # إنشاء جلسة الدفع
            checkout_session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": f"{booking.car.name} (1 day)",
                                "description": f"🚗 Trip: {booking.trip_location}",
                                "images": [f"{settings.DOMAIN}{booking.car.image.url}"],
                            },
                            "unit_amount": int(float(car.price) * 100),  # بالدولار
                            
                        },
                        "quantity": 1,
                    }
                ],
                success_url=f"{settings.DOMAIN}/payment/success/?booking={booking.id}",
                cancel_url=f"{settings.DOMAIN}/payment/cancel/?booking={booking.id}",
            )

            return JsonResponse({"url": checkout_session.url})
        except Exception as e:
            return JsonResponse({"error": str(e)})

    return JsonResponse({"error": "Invalid request"})






# ===========================
# SEARCH & COMPANIES
# ===========================
def search_cars(request):
    query = request.GET.get("q", "")

    cars = Car.objects.filter(
        Q(name__icontains=query) |
        Q(transmission__icontains=query) |
        Q(year__icontains=query),
        is_available=True   # ✅ فلترة السيارات المتاحة فقط
    )

    results = [{
        "id": car.id,
        "name": car.name,
        "year": car.year,
        "transmission": car.transmission,
        "mileage": car.mileage,
        "price": str(car.price),
        "image": car.image.url if car.image else "",
    } for car in cars]

    return JsonResponse({"results": results})



def companies_list(request):
    owners = User.objects.filter(role="owner", is_approved=True)
    return render(request, "companies.html", {"owners": owners})


def owner_cars(request, owner_id):
    owner = get_object_or_404(User, id=owner_id, role="owner")
    cars = Car.objects.filter(owner=owner)
    cars_count = cars.count()   # ✅ عدد السيارات
    return render(request, "owner_cars.html", {"owner": owner, "cars": cars,  "cars_count": cars_count})


def owner_profile(request, owner_id):
    owner = get_object_or_404(User, id=owner_id, role="owner")
    cars = Car.objects.filter(owner=owner)
    return render(request, "owner_cars.html", {"owner": owner, "cars": cars})


# ===========================
# CONTACT FORM
# ===========================
def contact(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        subject = request.POST.get("subject", "").strip()
        message = request.POST.get("message", "").strip()

        if not all([name, email, subject, message]):
            messages.error(request, " Please fill in all fields.")
            return redirect("contact")

        to_email = getattr(settings, "CONTACT_EMAIL", settings.DEFAULT_FROM_EMAIL)
        full_subject = f"[Royal Cars Contact] {subject}"
        full_message = f"From: {name} <{email}>\n\nMessage:\n{message}"

        try:
            send_mail(full_subject, full_message, settings.DEFAULT_FROM_EMAIL, [to_email])
            messages.success(request, " Your message has been sent successfully.")
        except Exception as e:
            messages.error(request, f" Failed to send message: {e}")

        return redirect("contact")

    return render(request, "contact.html", {"CONTACT_EMAIL": getattr(settings, "CONTACT_EMAIL", None)})



from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseForbidden
from .models import Booking, Contract

@login_required(login_url="login")
def contract_detail(request, booking_id):
    # Get the booking
    booking = get_object_or_404(Booking, id=booking_id)

    # Check ownership
    if booking.user != request.user:
        return HttpResponseForbidden("You are not allowed to view this contract.")

    # Get or create the contract
    contract, _ = Contract.objects.get_or_create(
        booking=booking,
        defaults={"notes": "", "total_price": booking.rental_days * booking.car.price}
    )

    # Render the template
    return render(request, "contract.html", {"contract": contract})


@login_required(login_url="login")
def create_review(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    # لو الحجز مش مدفوع أو فيه تقييم بالفعل → رجّعه للبروفايل
    if booking.status != "paid" or hasattr(booking, "review"):
        return redirect("profile")

    if request.method == "POST":
        rating = int(request.POST.get("rating", 5))
        comment = request.POST.get("comment", "")
        Review.objects.create(
            booking=booking,
            user=request.user,
            rating=rating,
            comment=comment
        )
        return redirect("profile")

    # ما عاد في صفحة مستقلة للتقييم
    return redirect("profile")


from django.db.models import Count, Avg

def cars_list(request):
    cars = Car.objects.all()
    sort = request.GET.get("sort")

    if sort == "popular":  # الأكثر طلباً
        cars = cars.annotate(num_bookings=Count("bookings")).order_by("-num_bookings")

    elif sort == "rating":  # الأعلى تقييماً
        cars = cars.annotate(avg_rating=Avg("bookings__review__rating")).order_by("-avg_rating")

    elif sort == "price_low":  # الأقل سعراً
        cars = cars.order_by("price")

    elif sort == "price_high":  # الأغلى
        cars = cars.order_by("-price")

    elif sort == "manual":  # ناقل حركة يدوي
        cars = cars.filter(transmission="MANUAL")

    elif sort == "auto":  # ناقل حركة أوتوماتيك
        cars = cars.filter(transmission="AUTO")

    elif sort == "economic":  # اقتصادي (مثلاً أقل من أو يساوي 50$)
        cars = cars.filter(price__lte=50)

    return render(request, "cars_list.html", {"cars": cars})


@login_required(login_url="login")
def edit_car(request, car_id):
    car = get_object_or_404(Car, id=car_id, owner=request.user)  # المالك فقط
    if request.method == "POST":
        car.name = request.POST.get("name")
        car.year = request.POST.get("year")
        car.transmission = request.POST.get("transmission")
        car.mileage = request.POST.get("mileage")
        car.price = request.POST.get("price")
        car.description = request.POST.get("description")

        if "image" in request.FILES:
            car.image = request.FILES["image"]

        car.save()
        messages.success(request, "Car updated successfully ")
        return redirect("owner_dashboard")

    return render(request, "edit_car.html", {"car": car})


@login_required(login_url="login")
def delete_car(request, car_id):
    car = get_object_or_404(Car, id=car_id, owner=request.user)  # المالك فقط
    if request.method == "POST":
        car.delete()
        messages.success(request, "Car deleted successfully ")
        return redirect("owner_dashboard")

    return render(request, "delete_car.html", {"car": car})

@login_required(login_url="login")
def approve_contract(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if request.method != "POST":
        messages.warning(request, "Please approve the contract to continue.")
        return redirect("my_bookings")

    # تأكد إن العقد موجود
    Contract.objects.get_or_create(booking=booking)

    # غيّر الحالة إلى مدفوع
    booking.status = Booking.STATUS_PAID
    booking.save(update_fields=["status"])

    messages.success(request, "✅ Contract approved. Your booking is now marked as paid.")
    return redirect("my_bookings")

@login_required(login_url="login")
def decline_contract(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if request.method == "POST":
        booking.status = Booking.STATUS_REJECTED
        booking.car.is_available = True
        booking.car.save(update_fields=["is_available"])
        booking.save(update_fields=["status"])

        messages.info(request, "❌ You declined the contract. Your booking has been canceled.")
        return redirect("my_bookings")

    return redirect("my_bookings")

@login_required(login_url="login")
def owner_bookings(request, owner_id):
    # تأكد أن المستخدم هو نفسه المالك
    if request.user.id != owner_id or request.user.role != "owner":
        return redirect("index")

    # كل الحجوزات الخاصة بسيارات المالك
    bookings = Booking.objects.filter(car__owner=request.user).select_related("car", "user")

    return render(request, "owner_bookings.html", {
        "bookings": bookings,
    })



from django.db.models.functions import TruncMonth

from collections import defaultdict
from decimal import Decimal


def admin_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)

        if user is not None and user.is_admin:
            login(request, user)
            return redirect("admin_dashboard")
        else:
            messages.error(request, "Invalid credentials or not an admin user.")

    return render(request, "admin_login.html")




@login_required(login_url="login")
def admin_dashboard(request):
    # تأكد أن المستخدم ادمن
    if not getattr(request.user, "is_admin", False):
        return redirect("index")

    # Users (بدون عدّ الـ Admins)
    total_users = User.objects.exclude(role=User.Roles.ADMIN).count()
    total_owners = User.objects.filter(role=User.Roles.OWNER).count()
    total_renters = User.objects.filter(role=User.Roles.USER).count()

    # Cars (خاصة بالملاك)
    total_cars = Car.objects.count()
    available_cars = Car.objects.filter(is_available=True).count()
    unavailable_cars = total_cars - available_cars

    # Bookings (خاصة بالمستخدمين والملاك)
    total_bookings = Booking.objects.count()
    pending = Booking.objects.filter(status=Booking.STATUS_PENDING).count()
    approved = Booking.objects.filter(status=Booking.STATUS_APPROVED).count()
    rejected = Booking.objects.filter(status=Booking.STATUS_REJECTED).count()
    paid = Booking.objects.filter(status=Booking.STATUS_PAID).count()

    # Payments (إجمالي المدفوعات)
    paid_contracts = Contract.objects.filter(booking__status=Booking.STATUS_PAID)
    total_payments = sum(c.total_price for c in paid_contracts)
    payments_count = paid_contracts.count() 

    # ✅ الأرباح = 10% من إجمالي المدفوعات
    profits = total_payments * Decimal("0.10")

    # Reviews
    total_reviews = Review.objects.count()
    avg_rating = Review.objects.aggregate(avg=Avg("rating"))["avg"] or 0

    # آخر 5 مستخدمين (بدون الادمن)
    recent_users = User.objects.exclude(role=User.Roles.ADMIN).order_by("-date_joined")[:5]

    # آخر 5 سيارات
    recent_cars = Car.objects.select_related("owner").order_by("-id")[:5]

    # آخر 5 حجوزات
    recent_bookings = Booking.objects.select_related("user", "car").order_by("-created_at")[:5]

    # بيانات للـ Chart.js (توزيع الحجوزات حسب الحالة)
    booking_status_data = {
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "paid": paid,
    }

    # بيانات للـ Chart.js (المدفوعات الشهرية)
    payments_by_month = (
        Contract.objects.filter(booking__status=Booking.STATUS_PAID)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )
    months = [p["month"].strftime("%b %Y") for p in payments_by_month]
    payments = [p["total"] for p in payments_by_month]

    # بيانات حجوزات المستخدمين (بدون الادمن)
    users = User.objects.filter(role=User.Roles.USER)
    user_booking_data = []
    for u in users:
        user_booking_data.append({
            "username": u.username,
            "pending": Booking.objects.filter(user=u, status=Booking.STATUS_PENDING).count(),
            "approved": Booking.objects.filter(user=u, status=Booking.STATUS_APPROVED).count(),
            "rejected": Booking.objects.filter(user=u, status=Booking.STATUS_REJECTED).count(),
            "paid": Booking.objects.filter(user=u, status=Booking.STATUS_PAID).count(),
        })

    # مبالغ الملاك
    owner_totals = defaultdict(Decimal)
    contracts = Contract.objects.filter(booking__status=Booking.STATUS_PAID).select_related("booking__car__owner")
    for c in contracts:
        owner_totals[c.booking.car.owner.username] += Decimal(c.total_price)
    owner_payments = [{"owner": k, "total": v} for k, v in owner_totals.items()]

    context = {
        # KPIs
        "total_users": total_users,
        "total_owners": total_owners,
        "total_renters": total_renters,
        "total_cars": total_cars,
        "available_cars": available_cars,
        "unavailable_cars": unavailable_cars,
        "total_bookings": total_bookings,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "paid": paid,
        "total_payments": total_payments,
        "profits": profits,   # ✅ الأرباح
        "total_reviews": total_reviews,
        "avg_rating": avg_rating,
        # Tables
        "recent_users": recent_users,
        "recent_cars": recent_cars,
        "recent_bookings": recent_bookings,
        # Charts
        "booking_status_data": booking_status_data,
        "months": months,
        "payments": payments,
        "user_booking_data": user_booking_data,
        "owner_payments": list(owner_payments),
        "payments_count": payments_count,

    }
    return render(request, "admin_dashboard.html", context)


from decimal import Decimal

import datetime
from django.http import HttpResponse
import openpyxl
from django.db.models import Avg

def export_admin_report_excel(request):
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    # فلترة حسب التاريخ
    user_filter = {}
    car_filter = {}
    booking_filter = {}
    contract_filter = {}
    review_filter = {}

    if start_date and end_date:
        user_filter = {"date_joined__date__range": [start_date, end_date]}
        car_filter = {"created_at__date__range": [start_date, end_date]}
        booking_filter = {"created_at__date__range": [start_date, end_date]}
        contract_filter = {"created_at__date__range": [start_date, end_date]}
        review_filter = {"created_at__date__range": [start_date, end_date]}

    # Users
    total_users = User.objects.exclude(role=User.Roles.ADMIN).filter(**user_filter).count()
    total_owners = User.objects.filter(role=User.Roles.OWNER, **user_filter).count()
    total_regulars = User.objects.filter(role=User.Roles.USER, **user_filter).count()

    # Cars
    total_cars = Car.objects.filter(**car_filter).count()
    available_cars = Car.objects.filter(is_available=True, **car_filter).count()
    unavailable_cars = total_cars - available_cars

    # Bookings
    bookings = Booking.objects.filter(**booking_filter)
    total_bookings = bookings.count()
    pending = bookings.filter(status=Booking.STATUS_PENDING).count()
    approved = bookings.filter(status=Booking.STATUS_APPROVED).count()
    rejected = bookings.filter(status=Booking.STATUS_REJECTED).count()
    paid = bookings.filter(status=Booking.STATUS_PAID).count()

    # Payments
    contracts = Contract.objects.filter(booking__status=Booking.STATUS_PAID, **contract_filter)
    total_payments = sum(c.total_price for c in contracts)
    payments_count = contracts.count()
    profits = total_payments * Decimal("0.10")


    # Reviews
    reviews = Review.objects.filter(**review_filter)
    total_reviews = reviews.count()
    avg_rating = reviews.aggregate(avg=Avg("rating"))["avg"] or 0

    # إنشاء ملف Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Admin Report"

    # العناوين
    ws.append(["Metric", "Value"])
    ws.append(["Total Users", total_users])
    ws.append(["Owners", total_owners])
    ws.append(["Regular Users", total_regulars])
    ws.append(["Total Cars", total_cars])
    ws.append(["Available Cars", available_cars])
    ws.append(["Unavailable Cars", unavailable_cars])
    ws.append(["Total Bookings", total_bookings])
    ws.append(["Pending", pending])
    ws.append(["Approved", approved])
    ws.append(["Rejected", rejected])
    ws.append(["Paid", paid])
    ws.append(["Payments Count", payments_count])
    ws.append(["Total Payments", float(total_payments)])
    ws.append(["Profits (10%)", float(profits)])
    ws.append(["Total Reviews", total_reviews])
    ws.append(["Average Rating", round(avg_rating, 1)])

    # تجهيز الاستجابة
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = f"admin_report_{datetime.date.today()}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response



import datetime
from decimal import Decimal
from django.http import HttpResponse
from django.db.models import Avg
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

def export_admin_report_pdf(request):
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    # فلترة حسب التاريخ
    user_filter = {}
    car_filter = {}
    booking_filter = {}
    contract_filter = {}
    review_filter = {}

    if start_date and end_date:
        user_filter = {"date_joined__date__range": [start_date, end_date]}
        car_filter = {"created_at__date__range": [start_date, end_date]}
        booking_filter = {"created_at__date__range": [start_date, end_date]}
        contract_filter = {"created_at__date__range": [start_date, end_date]}
        review_filter = {"created_at__date__range": [start_date, end_date]}

    # Users
    total_users = User.objects.exclude(role=User.Roles.ADMIN).filter(**user_filter).count()
    total_owners = User.objects.filter(role=User.Roles.OWNER, **user_filter).count()
    total_regulars = User.objects.filter(role=User.Roles.USER, **user_filter).count()

    # Cars
    total_cars = Car.objects.filter(**car_filter).count()
    available_cars = Car.objects.filter(is_available=True, **car_filter).count()
    unavailable_cars = total_cars - available_cars

    # Bookings
    bookings = Booking.objects.filter(**booking_filter)
    total_bookings = bookings.count()
    pending = bookings.filter(status=Booking.STATUS_PENDING).count()
    approved = bookings.filter(status=Booking.STATUS_APPROVED).count()
    rejected = bookings.filter(status=Booking.STATUS_REJECTED).count()
    paid = bookings.filter(status=Booking.STATUS_PAID).count()

    # Payments
    contracts = Contract.objects.filter(booking__status=Booking.STATUS_PAID, **contract_filter)
    total_payments = sum(c.total_price for c in contracts)
    payments_count = contracts.count()
    profits = total_payments * Decimal("0.10")

    # Reviews
    reviews = Review.objects.filter(**review_filter)
    total_reviews = reviews.count()
    avg_rating = reviews.aggregate(avg=Avg("rating"))["avg"] or 0

    # تجهيز ملف PDF
    response = HttpResponse(content_type="application/pdf")
    filename = f"admin_report_{datetime.date.today()}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    y = height - 50

    p.setFont("Helvetica-Bold", 14)
    p.drawString(200, y, "Admin Report")
    y -= 40

    p.setFont("Helvetica", 12)

    # Users
    p.drawString(50, y, f"Total Users: {total_users} (Owners: {total_owners}, Regular: {total_regulars})")
    y -= 20

    # Cars
    p.drawString(50, y, f"Total Cars: {total_cars} (Available: {available_cars}, Unavailable: {unavailable_cars})")
    y -= 20

    # Bookings
    p.drawString(50, y, f"Total Bookings: {total_bookings} (Pending: {pending}, Approved: {approved}, Rejected: {rejected}, Paid: {paid})")
    y -= 20

    # Payments
    p.drawString(50, y, f"Payments Count: {payments_count}")
    y -= 20
    p.drawString(50, y, f"Total Payments: ${total_payments:.2f}")
    y -= 20
    p.drawString(50, y, f"Profits (10%): ${profits:.2f}")
    y -= 20

    # Reviews
    p.drawString(50, y, f"Total Reviews: {total_reviews}, Average Rating: {avg_rating:.1f}")
    y -= 40

    p.showPage()
    p.save()
    return response
