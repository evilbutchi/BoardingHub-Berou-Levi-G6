from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Bill, Contract, Payment, Room, UtilityReading
from .services import due_date_for, sync_bill

User = get_user_model()
PASSWORD = "Str0ng-Pass-9271"


def make_user(username, role):
    return User.objects.create_user(
        username=username,
        password=PASSWORD,
        role=role,
        email=f"{username}@example.com",
        first_name=username.title(),
        last_name="Test",
        contact_number="09171234567",
    )


class BillingTestCase(TestCase):
    """Creates one user per role and helpers shared by the tests below."""

    @classmethod
    def setUpTestData(cls):
        cls.landlord = make_user("landlord", "landlord")
        cls.caretaker = make_user("caretaker", "caretaker")
        cls.tenant = make_user("tenant", "tenant")
        cls.other_tenant = make_user("othertenant", "tenant")

    TODAY = date(2026, 11, 23)

    def setUp(self):
        # Pin "today" so due dates, overdue status and month limits are predictable.
        patcher = patch("django.utils.timezone.localdate", return_value=self.TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)

    def make_room(self, number="101"):
        return Room.objects.create(room_number=number, created_by=self.landlord)

    def make_contract(self, tenant=None, room=None, **kwargs):
        defaults = dict(
            tenant=tenant or self.tenant,
            room=room or self.make_room(),
            monthly_rate=Decimal("3000.00"),
            deposit=Decimal("3000.00"),
            start_date=date(2026, 1, 1),
            created_by=self.landlord,
        )
        defaults.update(kwargs)
        return Contract.objects.create(**defaults)


# -------------------------------------------------------------------- rooms
class RoomTests(BillingTestCase):
    def test_landlord_can_create_room(self):
        self.login(self.landlord)
        resp = self.client.post(
            reverse("billing:room_create"), {"room_number": "a-1", "description": "Corner"}
        )
        self.assertRedirects(resp, reverse("billing:room_list"))
        room = Room.objects.get()
        self.assertEqual(room.room_number, "A-1")  # normalised to upper case
        self.assertEqual(room.created_by, self.landlord)

    def test_duplicate_room_number_rejected_case_insensitively(self):
        self.make_room("101")
        self.login(self.landlord)
        resp = self.client.post(reverse("billing:room_create"), {"room_number": "101 ", "description": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")
        self.assertEqual(Room.objects.count(), 1)

    def test_room_number_required(self):
        self.login(self.landlord)
        resp = self.client.post(reverse("billing:room_create"), {"room_number": "", "description": "x"})
        self.assertContains(resp, "This field is required")

    def test_landlord_can_edit_room(self):
        room = self.make_room("101")
        self.login(self.landlord)
        self.client.post(reverse("billing:room_edit", args=[room.pk]), {"room_number": "102", "description": "New"})
        room.refresh_from_db()
        self.assertEqual((room.room_number, room.description), ("102", "New"))

    def test_delete_room_without_history(self):
        room = self.make_room()
        self.login(self.landlord)
        self.client.post(reverse("billing:room_delete", args=[room.pk]))
        self.assertFalse(Room.objects.exists())

    def test_cannot_delete_room_with_contract_history(self):
        contract = self.make_contract()
        self.login(self.landlord)
        resp = self.client.post(reverse("billing:room_delete", args=[contract.room.pk]), follow=True)
        self.assertTrue(Room.objects.filter(pk=contract.room.pk).exists())
        self.assertContains(resp, "contract history")

    def test_delete_requires_post(self):
        room = self.make_room()
        self.login(self.landlord)
        resp = self.client.get(reverse("billing:room_delete", args=[room.pk]))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Room.objects.exists())

    def test_room_list_shows_occupancy(self):
        contract = self.make_contract()
        self.make_room("102")
        self.login(self.landlord)
        resp = self.client.get(reverse("billing:room_list"))
        self.assertContains(resp, "Occupied")
        self.assertContains(resp, "Available")
        self.assertTrue(contract.room.is_occupied)


# ---------------------------------------------------------------- contracts
class ContractTests(BillingTestCase):
    def payload(self, room, tenant=None, **overrides):
        data = {
            "tenant": (tenant or self.tenant).pk,
            "room": room.pk,
            "monthly_rate": "3500.00",
            "deposit": "3500.00",
            "start_date": "2026-02-01",
            "end_date": "",
        }
        data.update(overrides)
        return data

    def test_landlord_creates_contract_and_room_becomes_occupied(self):
        room = self.make_room()
        self.login(self.landlord)
        resp = self.client.post(reverse("billing:contract_create"), self.payload(room))
        contract = Contract.objects.get()
        self.assertRedirects(resp, reverse("billing:contract_detail", args=[contract.pk]))
        self.assertEqual(contract.created_by, self.landlord)
        self.assertTrue(contract.is_active)
        self.assertEqual(contract.monthly_rate, Decimal("3500.00"))
        self.assertTrue(room.is_occupied)

    def test_form_only_offers_free_tenants_and_rooms(self):
        taken = self.make_contract()
        free_room = self.make_room("102")
        self.login(self.landlord)
        resp = self.client.get(reverse("billing:contract_create"))
        form = resp.context["form"]
        self.assertNotIn(taken.tenant, form.fields["tenant"].queryset)
        self.assertIn(self.other_tenant, form.fields["tenant"].queryset)
        self.assertNotIn(taken.room, form.fields["room"].queryset)
        self.assertIn(free_room, form.fields["room"].queryset)
        # Only tenants can be chosen, never landlords or caretakers.
        self.assertNotIn(self.caretaker, form.fields["tenant"].queryset)

    def test_cannot_double_book_room_or_tenant(self):
        taken = self.make_contract()
        self.login(self.landlord)
        resp = self.client.post(
            reverse("billing:contract_create"), self.payload(taken.room, tenant=self.other_tenant)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context["form"], "room", "Select a valid choice. That choice is not one of the available choices.")
        self.assertEqual(Contract.objects.count(), 1)

    def test_database_blocks_second_active_contract_for_room(self):
        taken = self.make_contract()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_contract(tenant=self.other_tenant, room=taken.room)

    def test_validation_rules(self):
        room = self.make_room()
        self.login(self.landlord)
        url = reverse("billing:contract_create")

        resp = self.client.post(url, self.payload(room, monthly_rate="0"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["form"].errors["monthly_rate"])

        resp = self.client.post(url, self.payload(room, deposit="-5"))
        self.assertTrue(resp.context["form"].errors["deposit"])

        resp = self.client.post(url, self.payload(room, monthly_rate="abc"))
        self.assertTrue(resp.context["form"].errors["monthly_rate"])

        resp = self.client.post(url, self.payload(room, end_date="2026-01-01"))
        self.assertTrue(resp.context["form"].errors["end_date"])

        resp = self.client.post(url, self.payload(room, start_date=""))
        self.assertTrue(resp.context["form"].errors["start_date"])
        self.assertFalse(Contract.objects.exists())

    def test_edit_updates_rate_but_not_tenant_or_room(self):
        contract = self.make_contract()
        other_room = self.make_room("102")
        self.login(self.landlord)
        self.client.post(
            reverse("billing:contract_edit", args=[contract.pk]),
            self.payload(other_room, tenant=self.other_tenant, monthly_rate="4000.00", start_date="2026-01-01"),
        )
        contract.refresh_from_db()
        self.assertEqual(contract.monthly_rate, Decimal("4000.00"))
        self.assertEqual(contract.tenant, self.tenant)
        self.assertNotEqual(contract.room, other_room)

    def test_end_contract_frees_room_and_tenant(self):
        contract = self.make_contract()
        self.login(self.landlord)
        self.client.post(reverse("billing:contract_end", args=[contract.pk]))
        contract.refresh_from_db()
        self.assertFalse(contract.is_active)
        self.assertIsNotNone(contract.end_date)
        self.assertFalse(contract.room.is_occupied)
        # Room and tenant can be used for a new contract again.
        self.make_contract(room=contract.room)

    def test_delete_contract(self):
        contract = self.make_contract()
        self.login(self.landlord)
        self.client.post(reverse("billing:contract_delete", args=[contract.pk]))
        self.assertFalse(Contract.objects.exists())

    def test_contract_list_filters(self):
        active = self.make_contract()
        ended = self.make_contract(tenant=self.other_tenant, room=self.make_room("102"), is_active=False)
        self.login(self.landlord)
        resp = self.client.get(reverse("billing:contract_list"))
        self.assertEqual(list(resp.context["contracts"]), [active])
        resp = self.client.get(reverse("billing:contract_list"), {"status": "ended"})
        self.assertEqual(list(resp.context["contracts"]), [ended])
        resp = self.client.get(reverse("billing:contract_list"), {"status": "all"})
        self.assertEqual(len(resp.context["contracts"]), 2)


class RoleAccessTests(BillingTestCase):
    def test_anonymous_users_are_sent_to_login(self):
        contract = self.make_contract()
        for name, args in [
            ("billing:room_list", []),
            ("billing:contract_list", []),
            ("billing:contract_detail", [contract.pk]),
            ("billing:my_contract", []),
        ]:
            resp = self.client.get(reverse(name, args=args))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn(reverse("accounts:login"), resp.url, name)

    def test_tenants_and_caretakers_cannot_manage_rooms_or_contracts(self):
        contract = self.make_contract()
        urls = [
            reverse("billing:room_list"),
            reverse("billing:room_create"),
            reverse("billing:contract_list"),
            reverse("billing:contract_create"),
            reverse("billing:contract_detail", args=[contract.pk]),
            reverse("billing:contract_edit", args=[contract.pk]),
        ]
        for user in (self.tenant, self.caretaker):
            self.client.logout()
            self.login(user)
            for url in urls:
                resp = self.client.get(url)
                self.assertRedirects(resp, user.get_dashboard_url(), fetch_redirect_response=False)
            # Write actions are blocked too.
            self.client.post(reverse("billing:contract_end", args=[contract.pk]))
            self.client.post(reverse("billing:contract_delete", args=[contract.pk]))
            contract.refresh_from_db()
            self.assertTrue(contract.is_active)

    def test_landlord_cannot_open_tenant_page(self):
        self.login(self.landlord)
        resp = self.client.get(reverse("billing:my_contract"))
        self.assertRedirects(resp, self.landlord.get_dashboard_url(), fetch_redirect_response=False)

    def test_tenant_sees_only_their_own_contract(self):
        mine = self.make_contract()
        self.make_contract(tenant=self.other_tenant, room=self.make_room("102"), monthly_rate=Decimal("9999.00"))
        self.login(self.tenant)
        resp = self.client.get(reverse("billing:my_contract"))
        self.assertEqual(resp.context["contract"], mine)
        self.assertNotContains(resp, "9,999")

    def test_tenant_without_contract_sees_friendly_message(self):
        self.login(self.tenant)
        resp = self.client.get(reverse("billing:my_contract"))
        self.assertContains(resp, "don't have an active contract")

    def test_navigation_matches_role(self):
        self.login(self.landlord)
        self.assertContains(self.client.get(reverse("accounts:dashboard_landlord")), reverse("billing:room_list"))
        self.client.logout()
        self.login(self.tenant)
        resp = self.client.get(reverse("accounts:dashboard_tenant"))
        self.assertContains(resp, reverse("billing:my_contract"))
        self.assertNotContains(resp, reverse("billing:room_list"))


# ----------------------------------------------------------------- billing flow
RATES = dict(
    ELECTRICITY_RATE_PER_KWH=Decimal("12.00"),
    WATER_RATE_PER_CUBIC_METER=Decimal("30.00"),
    BILL_DUE_DAY=10,
)


def reading_payload(month="2026-03", e_prev="100", e_cur="150", w_prev="10", w_cur="20"):
    return {
        "billing_month": month,
        "electricity_previous": e_prev,
        "electricity_current": e_cur,
        "water_previous": w_prev,
        "water_current": w_cur,
    }


@override_settings(**RATES)
class BillingFlowTestCase(BillingTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.caretaker2 = make_user("caretaker2", "caretaker")

    def setUp(self):
        super().setUp()
        self.contract = self.make_contract()  # tenant in room 101, rent 3000, from 2026-01-01

    def record(self, month="2026-03", by=None, contract=None, **kwargs):
        """Record a reading through the UI as the caretaker and return the response."""
        self.client.logout()
        self.login(by or self.caretaker)
        contract = contract or self.contract
        return self.client.post(reverse("billing:reading_create", args=[contract.pk]), reading_payload(month, **kwargs))

    def make_bill(self, month="2026-03", e_prev="100", e_cur="150", w_prev="10", w_cur="20", contract=None):
        contract = contract or self.contract
        reading = UtilityReading.objects.create(
            contract=contract,
            billing_month=date.fromisoformat(month + "-01"),
            electricity_previous=Decimal(e_prev),
            electricity_current=Decimal(e_cur),
            water_previous=Decimal(w_prev),
            water_current=Decimal(w_cur),
            recorded_by=self.caretaker,
        )
        return sync_bill(reading)


class ReadingTests(BillingFlowTestCase):
    def test_caretaker_records_reading_and_bill_is_generated(self):
        resp = self.record()
        self.assertRedirects(resp, reverse("billing:reading_list"))
        reading = UtilityReading.objects.get()
        self.assertEqual(reading.recorded_by, self.caretaker)
        self.assertEqual(reading.billing_month, date(2026, 3, 1))
        bill = reading.bill
        # 3000 rent + 50 kWh * 12 + 10 m3 * 30
        self.assertEqual(bill.rent_amount, Decimal("3000.00"))
        self.assertEqual(bill.electricity_amount, Decimal("600.00"))
        self.assertEqual(bill.water_amount, Decimal("300.00"))
        self.assertEqual(bill.total_amount, Decimal("3900.00"))
        self.assertEqual(bill.due_date, date(2026, 4, 10))
        self.assertEqual(bill.contract, self.contract)

    def test_due_date_is_the_10th_of_the_following_month(self):
        self.record(month="2026-11")
        self.assertEqual(Bill.objects.get().due_date, date(2026, 12, 10))

    def test_due_date_rolls_into_next_year_for_december(self):
        self.assertEqual(due_date_for(date(2026, 12, 1)), date(2027, 1, 10))

    def test_previous_values_are_carried_over_and_cannot_be_overridden(self):
        self.record()
        # The caretaker tries to type different "previous" values for the next month.
        self.record(month="2026-04", e_prev="0", e_cur="200", w_prev="0", w_cur="25")
        second = UtilityReading.objects.get(billing_month=date(2026, 4, 1))
        self.assertEqual(second.electricity_previous, Decimal("150.00"))
        self.assertEqual(second.water_previous, Decimal("20.00"))
        self.assertEqual(second.bill.electricity_amount, Decimal("600.00"))  # 50 kWh

    def test_meter_chain_continues_for_a_new_tenant_in_the_same_room(self):
        self.record()
        self.client.logout()
        self.login(self.landlord)
        self.client.post(reverse("billing:contract_end", args=[self.contract.pk]))
        new_contract = self.make_contract(
            tenant=self.other_tenant, room=self.contract.room, start_date=date(2026, 4, 1)
        )
        self.record(month="2026-04", contract=new_contract, e_cur="170", w_cur="22")
        reading = UtilityReading.objects.get(contract=new_contract)
        self.assertEqual(reading.electricity_previous, Decimal("150.00"))
        self.assertEqual(reading.bill.contract.tenant, self.other_tenant)

    def test_current_cannot_be_lower_than_previous(self):
        resp = self.record(e_cur="90")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "can&#x27;t be lower than the previous")
        resp = self.record(w_cur="5")
        self.assertContains(resp, "Current water reading")
        self.assertFalse(UtilityReading.objects.exists())

    def test_required_and_numeric_fields(self):
        resp = self.record(e_cur="")
        self.assertTrue(resp.context["form"].errors["electricity_current"])
        resp = self.record(w_cur="abc")
        self.assertTrue(resp.context["form"].errors["water_current"])
        resp = self.record(e_prev="-5", e_cur="10")
        self.assertTrue(resp.context["form"].errors["electricity_previous"])
        self.assertFalse(UtilityReading.objects.exists())

    def test_month_rules(self):
        resp = self.record(month="2025-12")  # before the contract started
        self.assertTrue(resp.context["form"].errors["billing_month"])
        resp = self.record(month="2026-12")  # month hasn't started yet
        self.assertContains(resp, "hasn&#x27;t started yet")
        resp = self.record(month="not-a-month")
        self.assertTrue(resp.context["form"].errors["billing_month"])
        self.assertFalse(UtilityReading.objects.exists())
        # A reading for a month at or before the room's last reading is refused.
        self.record(month="2026-03")
        resp = self.record(month="2026-03")
        self.assertContains(resp, "last reading is for March 2026")
        resp = self.record(month="2026-02")
        self.assertContains(resp, "last reading is for March 2026")
        self.assertEqual(UtilityReading.objects.count(), 1)

    def test_cannot_record_for_ended_contract(self):
        self.contract.is_active = False
        self.contract.save()
        self.login(self.caretaker)
        resp = self.client.get(reverse("billing:reading_create", args=[self.contract.pk]), follow=True)
        self.assertContains(resp, "has ended")

    def test_edit_latest_reading_recalculates_bill(self):
        self.record()
        reading = UtilityReading.objects.get()
        self.login(self.caretaker)
        resp = self.client.post(
            reverse("billing:reading_edit", args=[reading.pk]),
            reading_payload(e_prev="100", e_cur="200", w_prev="10", w_cur="20"),
        )
        self.assertRedirects(resp, reverse("billing:reading_list"))
        reading.refresh_from_db()
        self.assertEqual(reading.electricity_current, Decimal("200.00"))
        self.assertEqual(reading.bill.total_amount, Decimal("4500.00"))  # 3000 + 100*12 + 10*30
        self.assertEqual(Bill.objects.count(), 1)

    def test_edit_keeps_rates_and_rent_the_bill_was_created_with(self):
        self.record()
        reading = UtilityReading.objects.get()
        self.contract.monthly_rate = Decimal("9000.00")
        self.contract.save()
        with override_settings(ELECTRICITY_RATE_PER_KWH=Decimal("99.00")):
            self.client.post(
                reverse("billing:reading_edit", args=[reading.pk]),
                reading_payload(e_cur="160"),
            )
        reading.bill.refresh_from_db()
        self.assertEqual(reading.bill.rent_amount, Decimal("3000.00"))
        self.assertEqual(reading.bill.electricity_rate, Decimal("12.00"))
        self.assertEqual(reading.bill.electricity_amount, Decimal("720.00"))

    def test_only_latest_reading_of_a_room_can_change(self):
        self.record(month="2026-03")
        self.record(month="2026-04", e_cur="200", w_cur="25")
        first = UtilityReading.objects.get(billing_month=date(2026, 3, 1))
        self.login(self.caretaker)
        resp = self.client.post(reverse("billing:reading_edit", args=[first.pk]), reading_payload(e_cur="160"), follow=True)
        self.assertContains(resp, "Only the latest reading")
        resp = self.client.post(reverse("billing:reading_delete", args=[first.pk]), follow=True)
        self.assertContains(resp, "Only the latest reading")
        self.assertEqual(UtilityReading.objects.count(), 2)

    def test_reading_with_payment_is_locked(self):
        self.record()
        reading = UtilityReading.objects.get()
        Payment.objects.create(bill=reading.bill, amount=Decimal("100"), paid_on=self.TODAY, recorded_by=self.landlord)
        self.login(self.caretaker)
        resp = self.client.post(reverse("billing:reading_edit", args=[reading.pk]), reading_payload(e_cur="160"), follow=True)
        self.assertContains(resp, "already recorded")
        self.client.post(reverse("billing:reading_delete", args=[reading.pk]))
        self.assertTrue(UtilityReading.objects.exists())

    def test_caretaker_can_only_change_own_readings_but_landlord_can_change_any(self):
        self.record(by=self.caretaker)
        reading = UtilityReading.objects.get()
        self.client.logout()
        self.login(self.caretaker2)
        resp = self.client.post(reverse("billing:reading_delete", args=[reading.pk]), follow=True)
        self.assertContains(resp, "only change readings they recorded")
        self.assertTrue(UtilityReading.objects.exists())
        self.client.logout()
        self.login(self.landlord)
        self.client.post(reverse("billing:reading_delete", args=[reading.pk]))
        self.assertFalse(UtilityReading.objects.exists())
        self.assertFalse(Bill.objects.exists())  # the bill goes with its reading

    def test_delete_requires_post(self):
        self.record()
        reading = UtilityReading.objects.get()
        resp = self.client.get(reverse("billing:reading_delete", args=[reading.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_contract_with_readings_cannot_be_deleted(self):
        self.record()
        self.client.logout()
        self.login(self.landlord)
        resp = self.client.post(reverse("billing:contract_delete", args=[self.contract.pk]), follow=True)
        self.assertContains(resp, "can&#x27;t be deleted")
        self.assertTrue(Contract.objects.filter(pk=self.contract.pk).exists())

    def test_reading_list_shows_history_and_active_rooms(self):
        self.record()
        self.login(self.caretaker)
        resp = self.client.get(reverse("billing:reading_list"))
        self.assertContains(resp, "Record reading")
        self.assertContains(resp, "Mar 2026")


class BillAndPaymentTests(BillingFlowTestCase):
    def pay(self, bill, amount, **overrides):
        data = {"amount": amount, "paid_on": "2026-11-20", "method": "cash", "reference": ""}
        data.update(overrides)
        self.client.logout()
        self.login(self.landlord)
        return self.client.post(reverse("billing:payment_create", args=[bill.pk]), data)

    def fresh(self, bill):
        return Bill.objects.prefetch_related("payments").get(pk=bill.pk)

    def test_status_unpaid_partial_paid(self):
        bill = self.make_bill(month="2026-11")  # due 2026-12-10, still in the future
        self.assertEqual(self.fresh(bill).status, Bill.Status.UNPAID)
        self.pay(bill, "1000")
        bill = self.fresh(bill)
        self.assertEqual(bill.status, Bill.Status.PARTIAL)
        self.assertEqual(bill.amount_paid, Decimal("1000.00"))
        self.assertEqual(bill.balance, Decimal("2900.00"))
        self.pay(bill, "2900")
        bill = self.fresh(bill)
        self.assertEqual(bill.status, Bill.Status.PAID)
        self.assertEqual(bill.balance, Decimal("0.00"))
        self.assertEqual(bill.payments.count(), 2)

    def test_status_overdue_after_due_date_until_fully_paid(self):
        bill = self.make_bill(month="2026-03")  # due 2026-04-10, long past
        self.assertEqual(self.fresh(bill).status, Bill.Status.OVERDUE)
        self.pay(bill, "500")
        self.assertEqual(self.fresh(bill).status, Bill.Status.OVERDUE)  # partly paid but still late
        self.pay(bill, "3400")
        self.assertEqual(self.fresh(bill).status, Bill.Status.PAID)

    def test_payment_is_linked_to_the_landlord_who_recorded_it(self):
        bill = self.make_bill(month="2026-11")
        resp = self.pay(bill, "500", method="gcash", reference="GC-123")
        self.assertRedirects(resp, reverse("billing:bill_detail", args=[bill.pk]))
        payment = Payment.objects.get()
        self.assertEqual((payment.recorded_by, payment.bill, payment.method), (self.landlord, bill, "gcash"))

    def test_payment_validation(self):
        bill = self.make_bill(month="2026-11")
        for amount in ("0", "-50", "abc", "", "3900.01"):
            resp = self.pay(bill, amount)
            self.assertEqual(resp.status_code, 200, amount)
            self.assertTrue(resp.context["form"].errors["amount"], amount)
        resp = self.pay(bill, "100", paid_on="2026-12-01")
        self.assertTrue(resp.context["form"].errors["paid_on"])
        resp = self.pay(bill, "100", paid_on="")
        self.assertTrue(resp.context["form"].errors["paid_on"])
        resp = self.pay(bill, "100", method="barter")
        self.assertTrue(resp.context["form"].errors["method"])
        self.assertFalse(Payment.objects.exists())

    def test_cannot_overpay_across_several_payments(self):
        bill = self.make_bill(month="2026-11")
        self.pay(bill, "3000")
        resp = self.pay(bill, "901")
        self.assertContains(resp, "more than the remaining balance of ₱900.00")
        self.assertEqual(Payment.objects.count(), 1)

    def test_fully_paid_bill_takes_no_more_payments(self):
        bill = self.make_bill(month="2026-11")
        self.pay(bill, "3900")
        resp = self.client.get(reverse("billing:payment_create", args=[bill.pk]), follow=True)
        self.assertContains(resp, "already fully paid")

    def test_edit_payment_respects_the_other_payments(self):
        bill = self.make_bill(month="2026-11")
        self.pay(bill, "1000")
        self.pay(bill, "1000")
        second = Payment.objects.order_by("id").last()
        url = reverse("billing:payment_edit", args=[second.pk])
        data = {"amount": "2900", "paid_on": "2026-11-21", "method": "cash", "reference": ""}
        self.client.post(url, data)  # 1000 + 2900 = 3900, exactly the total
        second.refresh_from_db()
        self.assertEqual(second.amount, Decimal("2900.00"))
        resp = self.client.post(url, {**data, "amount": "2901"})
        self.assertTrue(resp.context["form"].errors["amount"])

    def test_delete_payment_restores_the_balance(self):
        bill = self.make_bill(month="2026-11")
        self.pay(bill, "3900")
        payment = Payment.objects.get()
        self.client.post(reverse("billing:payment_delete", args=[payment.pk]))
        self.assertEqual(self.fresh(bill).status, Bill.Status.UNPAID)

    def test_payment_delete_requires_post(self):
        bill = self.make_bill(month="2026-11")
        self.pay(bill, "100")
        resp = self.client.get(reverse("billing:payment_delete", args=[Payment.objects.get().pk]))
        self.assertEqual(resp.status_code, 405)

    def test_bill_list_filters_and_totals(self):
        overdue = self.make_bill(month="2026-03")
        current = self.make_bill(month="2026-11", e_prev="150", e_cur="200", w_prev="20", w_cur="30")
        self.pay(current, "3900")  # 3000 + 600 + 300 = 3900, fully paid
        self.login(self.landlord)
        resp = self.client.get(reverse("billing:bill_list"))
        self.assertEqual(resp.context["outstanding"], Decimal("3900.00"))
        self.assertEqual(resp.context["overdue_count"], 1)
        self.assertEqual(len(resp.context["bills"]), 2)
        resp = self.client.get(reverse("billing:bill_list"), {"status": "overdue"})
        self.assertEqual([b.pk for b in resp.context["bills"]], [overdue.pk])
        resp = self.client.get(reverse("billing:bill_list"), {"status": "paid"})
        self.assertEqual([b.pk for b in resp.context["bills"]], [current.pk])
        resp = self.client.get(reverse("billing:bill_list"), {"status": "nonsense"})
        self.assertEqual(len(resp.context["bills"]), 2)

    def test_bill_detail_shows_breakdown_to_landlord(self):
        bill = self.make_bill()
        self.login(self.landlord)
        resp = self.client.get(reverse("billing:bill_detail", args=[bill.pk]))
        self.assertContains(resp, "3,900.00")
        self.assertContains(resp, "Record payment")


class RoleScopeTests(BillingFlowTestCase):
    def setUp(self):
        super().setUp()
        self.my_bill = self.make_bill(month="2026-11")
        other_contract = self.make_contract(tenant=self.other_tenant, room=self.make_room("102"))
        self.other_bill = self.make_bill(
            month="2026-11", e_prev="0", e_cur="10", w_prev="0", w_cur="1", contract=other_contract
        )

    def test_tenant_sees_only_their_own_bills(self):
        self.login(self.tenant)
        resp = self.client.get(reverse("billing:my_bills"))
        self.assertEqual([b.pk for b in resp.context["bills"]], [self.my_bill.pk])
        self.assertEqual(resp.context["outstanding"], Decimal("3900.00"))

    def test_tenant_can_open_own_bill_but_not_someone_elses(self):
        self.login(self.tenant)
        self.assertEqual(self.client.get(reverse("billing:bill_detail", args=[self.my_bill.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("billing:bill_detail", args=[self.other_bill.pk])).status_code, 404)

    def test_tenant_sees_their_payment_history_without_edit_controls(self):
        Payment.objects.create(bill=self.my_bill, amount=Decimal("500"), paid_on=self.TODAY, recorded_by=self.landlord, reference="R-77")
        self.login(self.tenant)
        resp = self.client.get(reverse("billing:bill_detail", args=[self.my_bill.pk]))
        self.assertContains(resp, "R-77")
        self.assertNotContains(resp, "Record payment")
        self.assertNotContains(resp, "/payments/")

    def test_tenant_cannot_record_or_change_payments(self):
        payment = Payment.objects.create(bill=self.my_bill, amount=Decimal("500"), paid_on=self.TODAY, recorded_by=self.landlord)
        self.login(self.tenant)
        for url in (
            reverse("billing:payment_create", args=[self.my_bill.pk]),
            reverse("billing:payment_edit", args=[payment.pk]),
        ):
            self.assertRedirects(self.client.get(url), self.tenant.get_dashboard_url(), fetch_redirect_response=False)
        self.client.post(reverse("billing:payment_create", args=[self.my_bill.pk]), {"amount": "100", "paid_on": "2026-11-20", "method": "cash"})
        self.client.post(reverse("billing:payment_delete", args=[payment.pk]))
        self.assertEqual(Payment.objects.count(), 1)

    def test_tenant_cannot_use_readings_or_the_bill_list(self):
        self.login(self.tenant)
        for name in ("billing:reading_list", "billing:bill_list"):
            self.assertRedirects(self.client.get(reverse(name)), self.tenant.get_dashboard_url(), fetch_redirect_response=False)
        self.client.post(reverse("billing:reading_create", args=[self.my_bill.contract.pk]), reading_payload(month="2026-05"))
        self.assertEqual(UtilityReading.objects.filter(billing_month=date(2026, 5, 1)).count(), 0)

    def test_caretaker_cannot_see_bills_or_payments(self):
        self.login(self.caretaker)
        for url in (
            reverse("billing:bill_list"),
            reverse("billing:bill_detail", args=[self.my_bill.pk]),
            reverse("billing:payment_create", args=[self.my_bill.pk]),
        ):
            self.assertRedirects(self.client.get(url), self.caretaker.get_dashboard_url(), fetch_redirect_response=False)

    def test_anonymous_users_are_sent_to_login(self):
        for name, args in [
            ("billing:reading_list", []),
            ("billing:bill_list", []),
            ("billing:my_bills", []),
            ("billing:bill_detail", [self.my_bill.pk]),
            ("billing:payment_create", [self.my_bill.pk]),
        ]:
            resp = self.client.get(reverse(name, args=args))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn(reverse("accounts:login"), resp.url, name)


class DashboardTests(BillingFlowTestCase):
    def test_landlord_dashboard_totals(self):
        bill = self.make_bill(month="2026-03")  # overdue
        Payment.objects.create(bill=bill, amount=Decimal("900"), paid_on=self.TODAY, recorded_by=self.landlord)
        self.login(self.landlord)
        resp = self.client.get(reverse("accounts:dashboard_landlord"))
        self.assertEqual(resp.context["outstanding"], Decimal("3000.00"))
        self.assertEqual(resp.context["overdue_count"], 1)
        self.assertEqual(resp.context["occupied_count"], 1)
        self.assertContains(resp, "Recent bills")

    def test_caretaker_dashboard_lists_rooms_still_to_read(self):
        self.login(self.caretaker)
        resp = self.client.get(reverse("accounts:dashboard_caretaker"))
        self.assertEqual(resp.context["pending"], [self.contract])
        self.record(month="2026-11")
        self.login(self.caretaker)
        resp = self.client.get(reverse("accounts:dashboard_caretaker"))
        self.assertEqual(resp.context["pending"], [])
        self.assertEqual(resp.context["done_count"], 1)

    def test_tenant_dashboard_shows_balance_and_room(self):
        self.make_bill(month="2026-11")
        self.login(self.tenant)
        resp = self.client.get(reverse("accounts:dashboard_tenant"))
        self.assertEqual(resp.context["contract"], self.contract)
        self.assertEqual(resp.context["outstanding"], Decimal("3900.00"))
        self.assertContains(resp, "All bills")


class SeedDemoTests(BillingTestCase):
    def test_seed_demo_creates_usable_data_and_can_run_twice(self):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)
        self.assertEqual(Contract.objects.filter(is_active=True, tenant__username="demo_tenant").count(), 1)
        self.assertEqual(Bill.objects.count(), 2)
        paid = [b for b in Bill.objects.prefetch_related("payments") if b.status == Bill.Status.PAID]
        self.assertEqual(len(paid), 1)
        self.client.login(username="demo_tenant", password="Demo-Pass-1234")
        self.assertEqual(self.client.get(reverse("billing:my_bills")).status_code, 200)
