from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Room(models.Model):
    """A rentable room. Whether it is occupied is derived from its contracts."""

    room_number = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rooms_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["room_number"]

    @property
    def current_contract(self):
        return self.contracts.filter(is_active=True).select_related("tenant").first()

    @property
    def is_occupied(self):
        return self.contracts.filter(is_active=True).exists()

    def __str__(self):
        return f"Room {self.room_number}"


class Contract(models.Model):
    """Links one tenant to one room and fixes the monthly rate and deposit."""

    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contracts",
        limit_choices_to={"role": "tenant"},
    )
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="contracts")
    monthly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    deposit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contracts_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_active", "-start_date", "-id"]
        constraints = [
            # A room can only have one running contract, and so can a tenant.
            models.UniqueConstraint(
                fields=["room"], condition=Q(is_active=True), name="one_active_contract_per_room"
            ),
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(is_active=True),
                name="one_active_contract_per_tenant",
            ),
            models.CheckConstraint(
                condition=Q(monthly_rate__gt=0), name="contract_monthly_rate_positive"
            ),
            models.CheckConstraint(condition=Q(deposit__gte=0), name="contract_deposit_not_negative"),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=models.F("start_date")),
                name="contract_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.tenant.display_name} · {self.room}"


class UtilityReading(models.Model):
    """Meter readings for one billing month, recorded by a caretaker (or landlord).

    Readings are cumulative meter values: usage is `current - previous`. The
    room's meter carries on across tenants, so each reading continues from the
    last reading recorded for the same room.
    """

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="readings")
    billing_month = models.DateField(help_text="First day of the month being billed.")
    electricity_previous = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    electricity_current = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    water_previous = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    water_current = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="readings_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-billing_month", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "billing_month"], name="one_reading_per_contract_month"
            ),
            models.CheckConstraint(
                condition=Q(electricity_current__gte=models.F("electricity_previous")),
                name="reading_electricity_not_decreasing",
            ),
            models.CheckConstraint(
                condition=Q(water_current__gte=models.F("water_previous")),
                name="reading_water_not_decreasing",
            ),
        ]

    @property
    def electricity_used(self):
        return self.electricity_current - self.electricity_previous

    @property
    def water_used(self):
        return self.water_current - self.water_previous

    @property
    def is_latest_for_room(self):
        """Only the newest reading of a room may be changed, so the meter chain stays intact."""
        later = UtilityReading.objects.filter(contract__room_id=self.contract.room_id).filter(
            Q(billing_month__gt=self.billing_month)
            | Q(billing_month=self.billing_month, pk__gt=self.pk)
        )
        return not later.exists()

    def __str__(self):
        return f"{self.contract.room} · {self.billing_month:%B %Y}"


class Bill(models.Model):
    """The monthly bill computed from a contract's rent and a utility reading.

    Amounts and rates are copied onto the bill when it is created, so later
    rate changes never rewrite old bills.
    """

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partial"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="bills")
    reading = models.OneToOneField(UtilityReading, on_delete=models.PROTECT, related_name="bill")
    billing_month = models.DateField()
    rent_amount = models.DecimalField(max_digits=10, decimal_places=2)
    electricity_units = models.DecimalField(max_digits=10, decimal_places=2)
    electricity_rate = models.DecimalField(max_digits=8, decimal_places=2)
    electricity_amount = models.DecimalField(max_digits=10, decimal_places=2)
    water_units = models.DecimalField(max_digits=10, decimal_places=2)
    water_rate = models.DecimalField(max_digits=8, decimal_places=2)
    water_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-billing_month", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "billing_month"], name="one_bill_per_contract_month"),
        ]

    @property
    def amount_paid(self):
        # Sums in Python so a prefetch of `payments` avoids one query per bill.
        return sum((p.amount for p in self.payments.all()), Decimal("0.00"))

    @property
    def balance(self):
        return self.total_amount - self.amount_paid

    @property
    def status(self):
        if self.balance <= 0:
            return self.Status.PAID
        if self.due_date < timezone.localdate():
            return self.Status.OVERDUE
        if self.amount_paid > 0:
            return self.Status.PARTIAL
        return self.Status.UNPAID

    @property
    def status_label(self):
        return self.Status(self.status).label

    def __str__(self):
        return f"Bill {self.billing_month:%B %Y} · {self.contract}"


class Payment(models.Model):
    """A payment the landlord received against a bill (several allowed per bill)."""

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        GCASH = "gcash", "GCash"
        BANK = "bank_transfer", "Bank transfer"
        OTHER = "other", "Other"

    bill = models.ForeignKey(Bill, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    paid_on = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(max_length=100, blank=True, help_text="Receipt or reference number, if any.")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"₱{self.amount} on {self.paid_on} for {self.bill}"
