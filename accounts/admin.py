from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("BoardingHub", {"fields": ("role", "contact_number", "profile_photo")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("BoardingHub", {"fields": ("email", "first_name", "last_name", "role", "contact_number")}),
    )
