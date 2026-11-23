from django.contrib import admin

from .models import Bill, Contract, Payment, Room, UtilityReading


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("room_number", "description", "created_by")
    search_fields = ("room_number",)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("tenant", "room", "monthly_rate", "start_date", "end_date", "is_active")
    list_filter = ("is_active",)


@admin.register(UtilityReading)
class UtilityReadingAdmin(admin.ModelAdmin):
    list_display = ("contract", "billing_month", "electricity_current", "water_current", "recorded_by")


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ("contract", "billing_month", "total_amount", "due_date")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("bill", "amount", "paid_on", "method", "recorded_by")
