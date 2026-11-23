from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Contract, Room

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
