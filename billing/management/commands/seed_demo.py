"""Create demo accounts, rooms, a contract and a few bills for trying the system out.

    python manage.py seed_demo

Safe to run more than once. These accounts use a known password, so only use
this on a development database.
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from billing.models import Contract, Payment, Room, UtilityReading
from billing.services import sync_bill

DEMO_PASSWORD = "Demo-Pass-1234"

def add_months(day, months):
    """First day of the month that is `months` after (or before, if negative) `day`'s month."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


ACCOUNTS = [
    ("demo_landlord", "landlord", "Lara", "Landlord"),
    ("demo_caretaker", "caretaker", "Carlo", "Caretaker"),
    ("demo_tenant", "tenant", "Tina", "Tenant"),
    ("demo_tenant2", "tenant", "Tomas", "Tenant"),
]


class Command(BaseCommand):
    help = "Create demo accounts (password: %s), rooms, a contract and sample bills." % DEMO_PASSWORD

    @transaction.atomic
    def handle(self, *args, **options):
        users = {}
        for username, role, first, last in ACCOUNTS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "role": role,
                    "first_name": first,
                    "last_name": last,
                    "email": f"{username}@example.com",
                    "contact_number": "09171234567",
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            users[username] = user

        landlord, caretaker = users["demo_landlord"], users["demo_caretaker"]
        for number in ("101", "102", "103"):
            Room.objects.get_or_create(room_number=number, defaults={"created_by": landlord})

        room = Room.objects.get(room_number="101")
        today = timezone.localdate()
        start = add_months(today, -2)  # contract began two months ago
        contract, created = Contract.objects.get_or_create(
            room=room,
            is_active=True,
            defaults={
                "tenant": users["demo_tenant"],
                "monthly_rate": Decimal("3500.00"),
                "deposit": Decimal("3500.00"),
                "start_date": start,
                "created_by": landlord,
            },
        )
        if created:
            e, w = Decimal("100"), Decimal("10")
            for offset in range(2):  # the two months before the current one
                month = add_months(start, offset)
                reading = UtilityReading.objects.create(
                    contract=contract,
                    billing_month=month,
                    electricity_previous=e,
                    electricity_current=e + 60,
                    water_previous=w,
                    water_current=w + 8,
                    recorded_by=caretaker,
                )
                e, w = e + 60, w + 8
                bill = sync_bill(reading)
                if offset == 0:
                    Payment.objects.create(
                        bill=bill, amount=bill.total_amount, paid_on=bill.due_date if bill.due_date <= today else today,
                        method=Payment.Method.GCASH, reference="DEMO-0001", recorded_by=landlord,
                    )

        self.stdout.write(self.style.SUCCESS(f"Demo data ready. Log in with password: {DEMO_PASSWORD}"))
        for username, role, *_ in ACCOUNTS:
            self.stdout.write(f"  {role:<10} {username}")
