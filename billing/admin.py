from django.contrib import admin

from .models import Contract, Room


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("room_number", "description", "created_by")
    search_fields = ("room_number",)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("tenant", "room", "monthly_rate", "start_date", "end_date", "is_active")
    list_filter = ("is_active",)
