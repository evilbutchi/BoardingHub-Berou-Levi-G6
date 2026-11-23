"""Utility readings, bills and payments.

Caretakers record readings, which generate bills. The landlord records payments.
Tenants can only read their own bills and payment history.
"""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User

from .forms import PaymentForm, ReadingForm
from .models import Bill, Contract, Payment, UtilityReading
from .services import bills_with_payments, latest_reading_for_room, summarize, sync_bill

LANDLORD = User.Role.LANDLORD
CARETAKER = User.Role.CARETAKER
TENANT = User.Role.TENANT

STATUS_FILTERS = ("all", "unpaid", "partial", "overdue", "paid")


# -------------------------------------------------------------------- readings
def _reading_block_reason(user, reading):
    """Why this user can't edit or delete the reading, or None if they can."""
    if user.role == CARETAKER and reading.recorded_by_id != user.pk:
        return "Caretakers can only change readings they recorded."
    if not reading.is_latest_for_room:
        return (
            "Only the latest reading of a room can be changed, because later readings "
            "continue from it."
        )
    bill = getattr(reading, "bill", None)
    if bill and bill.payments.exists():
        return "A payment was already recorded against this bill, so the reading is locked."
    return None


@role_required(LANDLORD, CARETAKER)
def reading_list(request):
    active = Contract.objects.filter(is_active=True).select_related("tenant", "room").order_by("room__room_number")
    rows = [{"contract": c, "latest": latest_reading_for_room(c.room_id)} for c in active]

    readings = UtilityReading.objects.select_related(
        "contract__tenant", "contract__room", "recorded_by", "bill"
    )
    for reading in readings:
        reading.block_reason = _reading_block_reason(request.user, reading)
    return render(request, "billing/reading_list.html", {"rows": rows, "readings": readings})


@role_required(LANDLORD, CARETAKER)
def reading_create(request, contract_pk):
    contract = get_object_or_404(Contract.objects.select_related("tenant", "room"), pk=contract_pk)
    if not contract.is_active:
        messages.error(request, "That contract has ended, so no new readings can be recorded.")
        return redirect("billing:reading_list")

    form = ReadingForm(
        request.POST if request.method == "POST" else None,
        instance=UtilityReading(contract=contract),
        contract=contract,
    )
    if request.method == "POST":
        if form.is_valid():
            with transaction.atomic():
                reading = form.save(commit=False)
                reading.recorded_by = request.user
                reading.save()
                bill = sync_bill(reading)
            messages.success(
                request,
                f"Reading saved. Bill for {bill.billing_month:%B %Y} generated: "
                f"₱{bill.total_amount:,.2f}.",
            )
            return redirect("billing:reading_list")
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "billing/reading_form.html", {"form": form, "contract": contract, "reading": None})


@role_required(LANDLORD, CARETAKER)
def reading_edit(request, pk):
    reading = get_object_or_404(UtilityReading.objects.select_related("contract__room", "contract__tenant"), pk=pk)
    reason = _reading_block_reason(request.user, reading)
    if reason:
        messages.error(request, reason)
        return redirect("billing:reading_list")

    form = ReadingForm(
        request.POST if request.method == "POST" else None,
        instance=reading,
        contract=reading.contract,
    )
    if request.method == "POST":
        if form.is_valid():
            with transaction.atomic():
                form.save()
                bill = sync_bill(reading)
            messages.success(request, f"Reading updated. The bill is now ₱{bill.total_amount:,.2f}.")
            return redirect("billing:reading_list")
        messages.error(request, "Please fix the errors below and try again.")
    return render(
        request,
        "billing/reading_form.html",
        {"form": form, "contract": reading.contract, "reading": reading},
    )


@role_required(LANDLORD, CARETAKER)
@require_POST
def reading_delete(request, pk):
    reading = get_object_or_404(UtilityReading, pk=pk)
    reason = _reading_block_reason(request.user, reading)
    if reason:
        messages.error(request, reason)
        return redirect("billing:reading_list")
    with transaction.atomic():
        Bill.objects.filter(reading=reading).delete()
        reading.delete()
    messages.success(request, "Reading and its bill were deleted.")
    return redirect("billing:reading_list")


# ----------------------------------------------------------------------- bills
@role_required(LANDLORD)
def bill_list(request):
    status = request.GET.get("status", "all")
    if status not in STATUS_FILTERS:
        status = "all"
    bills = list(bills_with_payments())
    totals = summarize(bills)
    if status != "all":
        bills = [b for b in bills if b.status == status]
    return render(
        request,
        "billing/bill_list.html",
        {"bills": bills, "status": status, "filters": STATUS_FILTERS, **totals},
    )


@role_required(LANDLORD, TENANT)
def bill_detail(request, pk):
    bills = bills_with_payments()
    if request.user.role == TENANT:
        # A tenant asking for someone else's bill gets a 404, same as a bill that doesn't exist.
        bills = bills.filter(contract__tenant=request.user)
    bill = get_object_or_404(bills, pk=pk)
    return render(request, "billing/bill_detail.html", {"bill": bill, "payments": bill.payments.all()})


@role_required(TENANT)
def my_bills(request):
    bills = list(bills_with_payments().filter(contract__tenant=request.user))
    totals = summarize(bills)
    return render(request, "billing/my_bills.html", {"bills": bills, **totals})


# -------------------------------------------------------------------- payments
@role_required(LANDLORD)
def payment_create(request, bill_pk):
    bill = get_object_or_404(bills_with_payments(), pk=bill_pk)
    if bill.balance <= 0:
        messages.info(request, "This bill is already fully paid.")
        return redirect("billing:bill_detail", pk=bill.pk)

    form = PaymentForm(request.POST if request.method == "POST" else None, bill=bill)
    if request.method == "POST":
        if form.is_valid():
            payment = form.save(commit=False)
            payment.bill = bill
            payment.recorded_by = request.user
            payment.save()
            messages.success(request, f"Payment of ₱{payment.amount:,.2f} recorded.")
            return redirect("billing:bill_detail", pk=bill.pk)
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "billing/payment_form.html", {"form": form, "bill": bill, "payment": None})


@role_required(LANDLORD)
def payment_edit(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("bill"), pk=pk)
    bill = get_object_or_404(bills_with_payments(), pk=payment.bill_id)
    form = PaymentForm(request.POST if request.method == "POST" else None, instance=payment, bill=bill)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Payment updated.")
            return redirect("billing:bill_detail", pk=bill.pk)
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "billing/payment_form.html", {"form": form, "bill": bill, "payment": payment})


@role_required(LANDLORD)
@require_POST
def payment_delete(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    bill_pk = payment.bill_id
    payment.delete()
    messages.success(request, "Payment deleted.")
    return redirect("billing:bill_detail", pk=bill_pk)
