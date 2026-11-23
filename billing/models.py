from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


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
