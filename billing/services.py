"""Billing rules in one place: meter chain, bill computation and payment totals."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db.models import Prefetch

from .models import Bill, Payment, UtilityReading

CENTS = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def month_start(value):
    return date(value.year, value.month, 1)


def latest_reading_for_room(room_id, exclude_pk=None):
    """The newest reading recorded for a room, whichever tenant it was billed to."""
    qs = UtilityReading.objects.filter(contract__room_id=room_id)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.order_by("-billing_month", "-id").first()


def due_date_for(billing_month):
    """Due on BILL_DUE_DAY of the month after the billing month."""
    year, month = billing_month.year, billing_month.month + 1
    if month == 13:
        year, month = year + 1, 1
    return date(year, month, min(settings.BILL_DUE_DAY, 28))


def sync_bill(reading):
    """Create the bill for a reading, or recompute it after the reading changed.

    A bill that already exists keeps its rent and utility rates, so editing a
    reading only changes the usage. A new bill takes the contract's monthly rate
    and the current utility rates from settings.
    """
    existing = Bill.objects.filter(reading=reading).first()
    if existing:
        rent = existing.rent_amount
        e_rate, w_rate = existing.electricity_rate, existing.water_rate
    else:
        rent = reading.contract.monthly_rate
        e_rate = settings.ELECTRICITY_RATE_PER_KWH
        w_rate = settings.WATER_RATE_PER_CUBIC_METER

    e_amount = money(reading.electricity_used * e_rate)
    w_amount = money(reading.water_used * w_rate)
    values = {
        "contract": reading.contract,
        "billing_month": reading.billing_month,
        "rent_amount": money(rent),
        "electricity_units": reading.electricity_used,
        "electricity_rate": e_rate,
        "electricity_amount": e_amount,
        "water_units": reading.water_used,
        "water_rate": w_rate,
        "water_amount": w_amount,
        "total_amount": money(rent) + e_amount + w_amount,
        "due_date": due_date_for(reading.billing_month),
    }
    bill, _ = Bill.objects.update_or_create(reading=reading, defaults=values)
    return bill


def bills_with_payments():
    """Bills with payments preloaded so status and balance don't query per row."""
    return Bill.objects.select_related("contract__tenant", "contract__room").prefetch_related(
        Prefetch("payments", queryset=Payment.objects.order_by("-paid_on", "-id"))
    )


def summarize(bills):
    """Totals for a dashboard. `bills` should come from bills_with_payments()."""
    outstanding = Decimal("0.00")
    overdue = 0
    for bill in bills:
        balance = bill.balance
        if balance > 0:
            outstanding += balance
            if bill.status == Bill.Status.OVERDUE:
                overdue += 1
    return {"outstanding": outstanding, "overdue_count": overdue}
