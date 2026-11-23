from django import forms
from django.db.models import Q

from accounts.models import User

from .models import Contract, Room


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
