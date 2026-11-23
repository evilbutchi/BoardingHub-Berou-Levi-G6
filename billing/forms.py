from decimal import Decimal

from django import forms
from django.utils import timezone

from accounts.models import User

from .models import Contract, Payment, Room, UtilityReading
from .services import latest_reading_for_room, money, month_start


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ("room_number", "description")
        help_texts = {"room_number": "For example 101 or A-2. Must be unique."}

    def clean_room_number(self):
        number = self.cleaned_data["room_number"].strip().upper()
        if not number:
            raise forms.ValidationError("Room number is required.")
        qs = Room.objects.filter(room_number__iexact=number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A room with this number already exists.")
        return number


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(**kwargs)


class ContractForm(forms.ModelForm):
    """Create or edit a contract.

    Tenant and room can only be chosen when creating. Only tenants and rooms
    without a running contract are offered. When editing they are locked, so
    a contract can't be silently moved to another person or room.
    """

    class Meta:
        model = Contract
        fields = ("tenant", "room", "monthly_rate", "deposit", "start_date", "end_date")
        widgets = {"start_date": DateInput(), "end_date": DateInput()}
        help_texts = {
            "end_date": "Optional. Leave blank for an open-ended contract.",
            "deposit": "Security deposit collected. Use 0 if none.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        editing = bool(self.instance.pk)

        tenants = User.objects.filter(role=User.Role.TENANT)
        rooms = Room.objects.all()
        if editing:
            for name in ("tenant", "room"):
                self.fields[name].disabled = True
        else:
            tenants = tenants.exclude(contracts__is_active=True)
            rooms = rooms.exclude(contracts__is_active=True)
        self.fields["tenant"].queryset = tenants
        self.fields["tenant"].label_from_instance = lambda u: f"{u.display_name} (@{u.username})"
        self.fields["room"].queryset = rooms

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date can't be before the start date.")
        return cleaned


class MonthInput(forms.DateInput):
    input_type = "month"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m")
        super().__init__(**kwargs)


class ReadingForm(forms.ModelForm):
    """Record or correct one month's meter readings for a contract.

    The room's meter is one continuous chain: the "previous" values come from
    the last reading recorded for the room and can't be typed over. Only the
    first reading of a room asks for its starting values.
    """

    billing_month = forms.DateField(
        input_formats=["%Y-%m"],
        widget=MonthInput(),
        label="Billing month",
        help_text="The month these readings are billed for.",
    )

    class Meta:
        model = UtilityReading
        fields = (
            "billing_month",
            "electricity_previous",
            "electricity_current",
            "water_previous",
            "water_current",
        )
        labels = {
            "electricity_previous": "Electricity: previous (kWh)",
            "electricity_current": "Electricity: current (kWh)",
            "water_previous": "Water: previous (m³)",
            "water_current": "Water: current (m³)",
        }

    def __init__(self, *args, contract, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        editing = bool(self.instance.pk)
        self.latest = latest_reading_for_room(contract.room_id, exclude_pk=self.instance.pk)

        if self.latest:
            for name, value in (
                ("electricity_previous", self.latest.electricity_current),
                ("water_previous", self.latest.water_current),
            ):
                self.fields[name].initial = value
                self.fields[name].disabled = True
                self.initial[name] = value
                self.fields[name].help_text = "Carried over from the last reading of this room."
        if editing:
            self.fields["billing_month"].disabled = True
        else:
            today = timezone.localdate()
            self.fields["billing_month"].initial = month_start(today)
        for name in ("electricity_previous", "electricity_current", "water_previous", "water_current"):
            self.fields[name].widget.attrs.setdefault("step", "0.01")
            self.fields[name].widget.attrs.setdefault("min", "0")

    def clean_billing_month(self):
        month = month_start(self.cleaned_data["billing_month"])
        if month > month_start(timezone.localdate()):
            raise forms.ValidationError("You can't bill a month that hasn't started yet.")
        if month < month_start(self.contract.start_date):
            raise forms.ValidationError(
                f"This contract started in {self.contract.start_date:%B %Y}. Pick that month or later."
            )
        if self.contract.end_date and month > month_start(self.contract.end_date):
            raise forms.ValidationError(
                f"This contract ended in {self.contract.end_date:%B %Y}. Pick that month or earlier."
            )
        if self.latest and month <= self.latest.billing_month:
            raise forms.ValidationError(
                f"This room's last reading is for {self.latest.billing_month:%B %Y}. "
                "Pick a later month."
            )
        return month

    def clean(self):
        cleaned = super().clean()
        for label, prev, cur in (
            ("electricity", "electricity_previous", "electricity_current"),
            ("water", "water_previous", "water_current"),
        ):
            previous, current = cleaned.get(prev), cleaned.get(cur)
            if previous is not None and current is not None and current < previous:
                self.add_error(cur, f"Current {label} reading can't be lower than the previous one ({previous}).")
        return cleaned


class PaymentForm(forms.ModelForm):
    """Record a payment against a bill. It can't exceed what is still owed."""

    class Meta:
        model = Payment
        fields = ("amount", "paid_on", "method", "reference")
        widgets = {"paid_on": DateInput()}

    def __init__(self, *args, bill, **kwargs):
        super().__init__(*args, **kwargs)
        self.bill = bill
        if not self.instance.pk:
            self.fields["paid_on"].initial = timezone.localdate()
        self.fields["amount"].widget.attrs.update({"step": "0.01", "min": "0.01"})
        self.max_amount = bill.total_amount - sum(
            (p.amount for p in bill.payments.all() if p.pk != self.instance.pk), Decimal("0.00")
        )
        self.fields["amount"].help_text = f"Remaining balance: ₱{self.max_amount:,.2f}"

    def clean_amount(self):
        amount = money(self.cleaned_data["amount"])
        if amount > self.max_amount:
            raise forms.ValidationError(
                f"That is more than the remaining balance of ₱{self.max_amount:,.2f}."
            )
        return amount

    def clean_paid_on(self):
        paid_on = self.cleaned_data["paid_on"]
        if paid_on > timezone.localdate():
            raise forms.ValidationError("The payment date can't be in the future.")
        return paid_on
