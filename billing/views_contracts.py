"""Rooms and contracts: Landlord-managed; Tenants can see their own contract."""

from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User

from .forms import ContractForm, RoomForm
from .models import Contract, Room
from .services import bills_with_payments

LANDLORD = User.Role.LANDLORD
TENANT = User.Role.TENANT


# ----------------------------------------------------------------------- rooms
@role_required(LANDLORD)
def room_list(request):
    rooms = Room.objects.prefetch_related("contracts__tenant")
    return render(request, "billing/room_list.html", {"rooms": rooms})


@role_required(LANDLORD)
def room_create(request):
    form = RoomForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if form.is_valid():
            room = form.save(commit=False)
            room.created_by = request.user
            room.save()
            messages.success(request, f"{room} was added.")
            return redirect("billing:room_list")
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "billing/room_form.html", {"form": form, "room": None})


@role_required(LANDLORD)
def room_edit(request, pk):
    room = get_object_or_404(Room, pk=pk)
    form = RoomForm(request.POST if request.method == "POST" else None, instance=room)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, f"{room} was updated.")
            return redirect("billing:room_list")
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "billing/room_form.html", {"form": form, "room": room})


@role_required(LANDLORD)
@require_POST
def room_delete(request, pk):
    room = get_object_or_404(Room, pk=pk)
    try:
        room.delete()
    except ProtectedError:
        messages.error(
            request, f"{room} can't be deleted because it has contract history."
        )
    else:
        messages.success(request, f"{room} was deleted.")
    return redirect("billing:room_list")


# ------------------------------------------------------------------- contracts
@role_required(LANDLORD)
def contract_list(request):
    status = request.GET.get("status", "active")
    contracts = Contract.objects.select_related("tenant", "room")
    if status == "active":
        contracts = contracts.filter(is_active=True)
    elif status == "ended":
        contracts = contracts.filter(is_active=False)
    else:
        status = "all"
    return render(
        request, "billing/contract_list.html", {"contracts": contracts, "status": status}
    )


@role_required(LANDLORD)
def contract_create(request):
    form = ContractForm(request.POST if request.method == "POST" else None)
    no_tenants = not form.fields["tenant"].queryset.exists()
    no_rooms = not form.fields["room"].queryset.exists()
    if request.method == "POST":
        if form.is_valid():
            with transaction.atomic():
                contract = form.save(commit=False)
                contract.created_by = request.user
                contract.is_active = True
                contract.save()
            messages.success(
                request,
                f"Contract created: {contract.tenant.display_name} is now in {contract.room}.",
            )
            return redirect("billing:contract_detail", pk=contract.pk)
        messages.error(request, "Please fix the errors below and try again.")
    return render(
        request,
        "billing/contract_form.html",
        {"form": form, "contract": None, "no_tenants": no_tenants, "no_rooms": no_rooms},
    )


@role_required(LANDLORD)
def contract_detail(request, pk):
    contract = get_object_or_404(Contract.objects.select_related("tenant", "room"), pk=pk)
    bills = bills_with_payments().filter(contract=contract)
    return render(request, "billing/contract_detail.html", {"contract": contract, "bills": bills})


@role_required(LANDLORD)
def contract_edit(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    form = ContractForm(request.POST if request.method == "POST" else None, instance=contract)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Contract updated.")
            return redirect("billing:contract_detail", pk=contract.pk)
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "billing/contract_form.html", {"form": form, "contract": contract})


@role_required(LANDLORD)
@require_POST
def contract_end(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    if not contract.is_active:
        messages.info(request, "That contract has already ended.")
    else:
        contract.is_active = False
        today = timezone.localdate()
        if contract.end_date is None or contract.end_date > today:
            contract.end_date = max(today, contract.start_date)
        contract.save()
        messages.success(request, f"Contract ended. {contract.room} is available again.")
    return redirect("billing:contract_detail", pk=contract.pk)


@role_required(LANDLORD)
@require_POST
def contract_delete(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    try:
        contract.delete()
    except ProtectedError:
        messages.error(
            request,
            "This contract has utility readings or bills, so it can't be deleted. "
            "End it instead.",
        )
        return redirect("billing:contract_detail", pk=pk)
    messages.success(request, "Contract deleted.")
    return redirect("billing:contract_list")


# ------------------------------------------------------------- tenant: my room
@role_required(TENANT)
def my_contract(request):
    contract = (
        Contract.objects.select_related("room")
        .filter(tenant=request.user, is_active=True)
        .first()
    )
    past = Contract.objects.select_related("room").filter(tenant=request.user, is_active=False)
    return render(request, "billing/my_contract.html", {"contract": contract, "past": past})
