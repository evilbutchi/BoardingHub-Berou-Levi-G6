from django.urls import path

from . import views_billing as billing
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
    # Utility readings (caretaker, landlord)
    path("readings/", billing.reading_list, name="reading_list"),
    path("readings/new/<int:contract_pk>/", billing.reading_create, name="reading_create"),
    path("readings/<int:pk>/edit/", billing.reading_edit, name="reading_edit"),
    path("readings/<int:pk>/delete/", billing.reading_delete, name="reading_delete"),
    # Bills and payments
    path("bills/", billing.bill_list, name="bill_list"),
    path("bills/<int:pk>/", billing.bill_detail, name="bill_detail"),
    path("bills/<int:bill_pk>/pay/", billing.payment_create, name="payment_create"),
    path("payments/<int:pk>/edit/", billing.payment_edit, name="payment_edit"),
    path("payments/<int:pk>/delete/", billing.payment_delete, name="payment_delete"),
    # Tenant
    path("my-room/", contracts.my_contract, name="my_contract"),
    path("my-bills/", billing.my_bills, name="my_bills"),
]
