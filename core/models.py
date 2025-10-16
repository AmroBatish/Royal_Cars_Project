from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.conf import settings


# =====================
# Custom User Model
# =====================
class User(AbstractUser):
    class Roles(models.TextChoices):
        USER = "user", "User"
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"

    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.USER)
    phone = models.CharField(max_length=32, blank=True)
    company_name = models.CharField(max_length=160, blank=True)
    license_image = models.ImageField(upload_to="licenses/", blank=True, null=True)
    is_approved = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_owner(self):
        return self.role == self.Roles.OWNER

    @property
    def is_admin(self):
        return self.role == self.Roles.ADMIN


# =====================
# Car Model
# =====================
class Car(models.Model):
    TRANSMISSION_CHOICES = [
        ("AUTO", "Automatic"),
        ("MANUAL", "Manual"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cars",
        limit_choices_to={"role": "owner"},
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    year = models.PositiveIntegerField()
    transmission = models.CharField(max_length=20, choices=TRANSMISSION_CHOICES)
    mileage = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to="cars/", blank=True, null=True)
    description = models.TextField(blank=True)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return f"{self.name} ({self.year})"

    class Meta:
        ordering = ["-year", "name"]


# =====================
# Booking Model
# =====================
class Booking(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_PAID = "paid"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_PAID, "Paid"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookings",
        null=True,
        blank=True,
    )
    car = models.ForeignKey(
        Car,
        on_delete=models.CASCADE,
        related_name="bookings",
        null=True,
        blank=True,
    )
    trip_location = models.CharField(max_length=300, null=True, blank=True)
    pickup_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distance_km = models.FloatField(null=True, blank=True)
    pickup_date = models.DateField()
    pickup_time = models.TimeField()
    return_date = models.DateField()  # تاريخ الإرجاع الجديد
    return_time = models.TimeField(null=True, blank=True)
    special_request = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(default=timezone.now)

    @property
    def rental_days(self):
        return (self.return_date - self.pickup_date).days

    def __str__(self):
        return f"Booking #{self.pk} - {self.user} → {self.car}"

    class Meta:
        ordering = ["-created_at"]



# =====================
# Owner Profile
# =====================
class OwnerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="owner_profile")
    company_name = models.CharField(max_length=160, blank=True)
    tax_no = models.CharField(max_length=64, blank=True, unique=True, null=True)

    def __str__(self):
        return f"Owner: {self.user.username}"


# =====================
# Contract
# =====================

class Contract(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="contract")
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    @property
    def total_price(self):
        return self.booking.rental_days * self.booking.car.price

    @property
    def owner_company(self):
        owner = self.booking.car.owner
        # لو عنده OwnerProfile نرجع company_name منه، وإلا fallback من User نفسه
        return getattr(getattr(owner, "owner_profile", None), "company_name", "") or owner.company_name or ""

    def __str__(self):
        return f"Contract for Booking #{self.booking.id}"
    

class Review(models.Model):
    booking = models.OneToOneField('Booking', on_delete=models.CASCADE, related_name='review')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.IntegerField(default=5)  # من 1 لـ 5
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
