from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

contact_number_validator = RegexValidator(
    regex=r"^\+?[0-9][0-9\s\-]{6,18}[0-9]$",
    message="Enter a valid contact number (digits, spaces or dashes; may start with +).",
)


class UserManager(DjangoUserManager):
    """Superusers created with `createsuperuser` become Landlords."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "landlord")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Custom user with a role. Passwords are hashed by Django's auth system."""

    class Role(models.TextChoices):
        LANDLORD = "landlord", "Landlord"
        CARETAKER = "caretaker", "Caretaker"
        TENANT = "tenant", "Tenant"

    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TENANT)
    contact_number = models.CharField(
        max_length=20, blank=True, validators=[contact_number_validator]
    )
    profile_photo = models.ImageField(upload_to="profile_photos/", blank=True, null=True)

    objects = UserManager()

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        # Keep emails lowercase so uniqueness is effectively case-insensitive.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_landlord(self):
        return self.role == self.Role.LANDLORD

    @property
    def is_caretaker(self):
        return self.role == self.Role.CARETAKER

    @property
    def is_tenant(self):
        return self.role == self.Role.TENANT

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = [p for p in (self.first_name, self.last_name) if p]
        if parts:
            return "".join(p[0] for p in parts[:2]).upper()
        return self.username[:2].upper()

    def get_dashboard_url(self):
        return reverse(f"accounts:dashboard_{self.role}")

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"
