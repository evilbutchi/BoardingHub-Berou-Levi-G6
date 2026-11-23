from django.urls import path

from . import views_contracts as contracts

app_name = "billing"

urlpatterns = [
    # Rooms (landlord)
    path("rooms/", contracts.room_list, name="room_list"),
    path("rooms/new/", contracts.room_create, name="room_create"),
    path("rooms/<int:pk>/edit/", contracts.room_edit, name="room_edit"),
    path("rooms/<int:pk>/delete/", contracts.room_delete, name="room_delete"),
    # Contracts (landlord)
    path("contracts/", contracts.contract_list, name="contract_list"),
    path("contracts/new/", contracts.contract_create, name="contract_create"),
    path("contracts/<int:pk>/", contracts.contract_detail, name="contract_detail"),
    path("contracts/<int:pk>/edit/", contracts.contract_edit, name="contract_edit"),
    path("contracts/<int:pk>/end/", contracts.contract_end, name="contract_end"),
    path("contracts/<int:pk>/delete/", contracts.contract_delete, name="contract_delete"),
    # Tenant
    path("my-room/", contracts.my_contract, name="my_contract"),
]
