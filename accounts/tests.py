import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

User = get_user_model()

PASSWORD = "Str0ng-Pass-9271"


def make_user(username, role, **extra):
    defaults = {
        "email": f"{username}@example.com",
        "first_name": username.title(),
        "last_name": "Test",
        "contact_number": "09171234567",
    }
    defaults.update(extra)
    return User.objects.create_user(username=username, password=PASSWORD, role=role, **defaults)


def valid_registration(**overrides):
    data = {
        "first_name": "Juan",
        "last_name": "Dela Cruz",
        "username": "juan",
        "email": "juan@example.com",
        "contact_number": "0917 123 4567",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    data.update(overrides)
    return data


class RegistrationTests(TestCase):
    url = reverse("accounts:register")

    def test_page_loads(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_successful_registration_creates_hashed_tenant(self):
        response = self.client.post(self.url, valid_registration(), follow=True)
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertContains(response, "Account created successfully")
        user = User.objects.get(username="juan")
        self.assertEqual(user.role, User.Role.TENANT)
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.password.startswith("pbkdf2_"))
        self.assertTrue(user.check_password(PASSWORD))

    def test_cannot_self_register_as_landlord(self):
        self.client.post(self.url, valid_registration(role="landlord"))
        self.assertEqual(User.objects.get(username="juan").role, User.Role.TENANT)

    def test_required_fields(self):
        response = self.client.post(self.url, {})
        for field in ("first_name", "last_name", "username", "email", "contact_number", "password1", "password2"):
            self.assertFormError(response.context["form"], field, "This field is required.")
        self.assertContains(response, "Please fix the errors below")
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_email(self):
        response = self.client.post(self.url, valid_registration(email="not-an-email"))
        self.assertTrue(response.context["form"].has_error("email"))
        self.assertFalse(User.objects.filter(username="juan").exists())

    def test_duplicate_username_case_insensitive(self):
        make_user("juan", User.Role.TENANT, email="other@example.com")
        response = self.client.post(self.url, valid_registration(username="JUAN"))
        self.assertTrue(response.context["form"].has_error("username"))

    def test_duplicate_email_case_insensitive(self):
        make_user("maria", User.Role.TENANT, email="juan@example.com")
        response = self.client.post(self.url, valid_registration(email="JUAN@Example.com"))
        self.assertFormError(response.context["form"], "email", "An account with this email already exists.")
        self.assertEqual(User.objects.count(), 1)

    def test_password_mismatch(self):
        response = self.client.post(self.url, valid_registration(password2="Different-Pass-1234"))
        self.assertTrue(response.context["form"].has_error("password2"))
        self.assertFalse(User.objects.filter(username="juan").exists())

    def test_weak_password_rejected(self):
        response = self.client.post(self.url, valid_registration(password1="12345678", password2="12345678"))
        self.assertTrue(response.context["form"].has_error("password2"))

    def test_invalid_contact_number(self):
        response = self.client.post(self.url, valid_registration(contact_number="abc"))
        self.assertTrue(response.context["form"].has_error("contact_number"))

    def test_logged_in_user_redirected_away(self):
        self.client.force_login(make_user("tina", User.Role.TENANT))
        self.assertRedirects(self.client.get(self.url), reverse("accounts:dashboard_tenant"))


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.login_url = reverse("accounts:login")
        self.tenant = make_user("tina", User.Role.TENANT)

    def test_login_success_redirects_to_role_dashboard(self):
        response = self.client.post(self.login_url, {"username": "tina", "password": PASSWORD}, follow=True)
        self.assertRedirects(response, reverse("accounts:dashboard_tenant"))
        self.assertContains(response, "Welcome back")

    def test_invalid_credentials_show_error(self):
        response = self.client.post(self.login_url, {"username": "tina", "password": "wrong-password"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a correct username and password")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_log_in(self):
        self.tenant.is_active = False
        self.tenant.save()
        response = self.client.post(self.login_url, {"username": "tina", "password": PASSWORD})
        # Django treats inactive accounts like bad credentials (no account hints leaked).
        self.assertContains(response, "Please enter a correct username and password")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_ends_session(self):
        self.client.force_login(self.tenant)
        response = self.client.post(reverse("accounts:logout"), follow=True)
        self.assertRedirects(response, self.login_url)
        self.assertContains(response, "logged out")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.client.force_login(self.tenant)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_next_param_is_honored_when_safe(self):
        url = f"{self.login_url}?next={reverse('accounts:profile')}"
        response = self.client.post(url, {"username": "tina", "password": PASSWORD, "next": reverse("accounts:profile")})
        self.assertRedirects(response, reverse("accounts:profile"))

    def test_external_next_param_is_ignored(self):
        response = self.client.post(
            self.login_url, {"username": "tina", "password": PASSWORD, "next": "https://evil.example.com/"}
        )
        self.assertRedirects(response, reverse("accounts:dashboard_tenant"))


class LoginRequiredTests(TestCase):
    def test_protected_pages_redirect_to_login(self):
        names = [
            "accounts:dashboard",
            "accounts:dashboard_landlord",
            "accounts:dashboard_caretaker",
            "accounts:dashboard_tenant",
            "accounts:profile",
            "accounts:profile_edit",
            "accounts:user_list",
            "accounts:caretaker_create",
        ]
        for name in names:
            with self.subTest(page=name):
                url = reverse(name)
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_home_redirects_anonymous_to_login(self):
        self.assertRedirects(self.client.get(reverse("accounts:home")), reverse("accounts:login"))


class RoleDashboardTests(TestCase):
    def setUp(self):
        self.landlord = make_user("lando", User.Role.LANDLORD)
        self.caretaker = make_user("care", User.Role.CARETAKER)
        self.tenant = make_user("tina", User.Role.TENANT)
        self.pages = {
            User.Role.LANDLORD: reverse("accounts:dashboard_landlord"),
            User.Role.CARETAKER: reverse("accounts:dashboard_caretaker"),
            User.Role.TENANT: reverse("accounts:dashboard_tenant"),
        }

    def test_dashboard_redirects_by_role(self):
        for user in (self.landlord, self.caretaker, self.tenant):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertRedirects(self.client.get(reverse("accounts:dashboard")), self.pages[user.role])

    def test_each_role_can_open_own_dashboard(self):
        for user in (self.landlord, self.caretaker, self.tenant):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.pages[user.role]).status_code, 200)

    def test_cannot_open_other_roles_dashboard_by_url(self):
        for user in (self.landlord, self.caretaker, self.tenant):
            self.client.force_login(user)
            for role, url in self.pages.items():
                if role == user.role:
                    continue
                with self.subTest(user=user.role, tried=role):
                    response = self.client.get(url, follow=True)
                    self.assertRedirects(response, self.pages[user.role])
                    self.assertContains(response, "don&#x27;t have permission")

    def test_navigation_fits_role(self):
        self.client.force_login(self.landlord)
        self.assertContains(self.client.get(self.pages[User.Role.LANDLORD]), reverse("accounts:user_list"))
        self.client.force_login(self.tenant)
        self.assertNotContains(self.client.get(self.pages[User.Role.TENANT]), reverse("accounts:user_list"))

    def test_only_landlord_can_manage_accounts(self):
        for user in (self.caretaker, self.tenant):
            self.client.force_login(user)
            for name in ("accounts:user_list", "accounts:caretaker_create"):
                with self.subTest(user=user.role, page=name):
                    response = self.client.get(reverse(name))
                    self.assertRedirects(response, self.pages[user.role], fetch_redirect_response=False)
        self.client.force_login(self.tenant)
        self.client.post(
            reverse("accounts:caretaker_create"),
            valid_registration(username="sneaky", email="sneaky@example.com"),
        )
        self.assertFalse(User.objects.filter(username="sneaky").exists())

    def test_landlord_creates_caretaker(self):
        self.client.force_login(self.landlord)
        response = self.client.post(
            reverse("accounts:caretaker_create"),
            valid_registration(username="newcare", email="newcare@example.com"),
            follow=True,
        )
        self.assertRedirects(response, reverse("accounts:user_list"))
        self.assertContains(response, "Caretaker account created")
        created = User.objects.get(username="newcare")
        self.assertEqual(created.role, User.Role.CARETAKER)
        self.assertTrue(created.password.startswith("pbkdf2_"))

    def test_createsuperuser_is_landlord(self):
        admin = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.assertEqual(admin.role, User.Role.LANDLORD)


class ProfileTests(TestCase):
    def setUp(self):
        self.tina = make_user("tina", User.Role.TENANT)
        self.other = make_user("other", User.Role.TENANT, first_name="Secret", email="secret@example.com")
        self.client.force_login(self.tina)

    def test_profile_shows_own_info_only(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "tina@example.com")
        self.assertNotContains(response, "secret@example.com")

    def test_no_url_exposes_another_users_profile(self):
        # Profile URLs carry no user id, so there is nothing to tamper with.
        self.assertEqual(self.client.get("/profile/%d/" % self.other.pk).status_code, 404)
        self.assertEqual(self.client.get("/profile/%d/edit/" % self.other.pk).status_code, 404)

    def test_update_profile(self):
        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Tina",
                "last_name": "Updated",
                "email": "TINA.NEW@example.com",
                "contact_number": "+63 917 555 1212",
            },
            follow=True,
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertContains(response, "Your profile was updated")
        self.tina.refresh_from_db()
        self.assertEqual(self.tina.last_name, "Updated")
        self.assertEqual(self.tina.email, "tina.new@example.com")
        self.assertEqual(self.tina.contact_number, "+63 917 555 1212")
        self.other.refresh_from_db()
        self.assertEqual(self.other.first_name, "Secret")

    def test_post_cannot_change_role_or_username(self):
        self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Tina", "last_name": "Test", "email": "tina@example.com",
                "contact_number": "09171234567", "role": "landlord", "username": "hacked",
            },
        )
        self.tina.refresh_from_db()
        self.assertEqual(self.tina.role, User.Role.TENANT)
        self.assertEqual(self.tina.username, "tina")

    def test_cannot_take_someone_elses_email(self):
        response = self.client.post(
            reverse("accounts:profile_edit"),
            {"first_name": "Tina", "last_name": "Test", "email": "Secret@Example.com", "contact_number": "09171234567"},
        )
        self.assertTrue(response.context["form"].has_error("email"))
        self.tina.refresh_from_db()
        self.assertEqual(self.tina.email, "tina@example.com")

    def test_keeping_own_email_is_allowed(self):
        response = self.client.post(
            reverse("accounts:profile_edit"),
            {"first_name": "Tina", "last_name": "Test", "email": "tina@example.com", "contact_number": "09171234567"},
        )
        self.assertRedirects(response, reverse("accounts:profile"))

    def test_required_fields_on_edit(self):
        response = self.client.post(reverse("accounts:profile_edit"), {})
        for field in ("first_name", "last_name", "email", "contact_number"):
            self.assertTrue(response.context["form"].has_error(field), field)

    def test_upload_profile_photo(self):
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "green").save(buf, "PNG")
        photo = SimpleUploadedFile("me.png", buf.getvalue(), content_type="image/png")
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            response = self.client.post(
                reverse("accounts:profile_edit"),
                {"first_name": "Tina", "last_name": "Test", "email": "tina@example.com",
                 "contact_number": "09171234567", "profile_photo": photo},
            )
            self.assertRedirects(response, reverse("accounts:profile"))
            self.tina.refresh_from_db()
            self.assertTrue(self.tina.profile_photo.name.startswith("profile_photos/"))

    def test_rejects_non_image_upload(self):
        fake = SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain")
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            response = self.client.post(
                reverse("accounts:profile_edit"),
                {"first_name": "Tina", "last_name": "Test", "email": "tina@example.com",
                 "contact_number": "09171234567", "profile_photo": fake},
            )
        self.assertTrue(response.context["form"].has_error("profile_photo"))

    def test_rejects_oversized_photo(self):
        big = SimpleUploadedFile("big.png", b"x" * (2 * 1024 * 1024 + 1), content_type="image/png")
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            response = self.client.post(
                reverse("accounts:profile_edit"),
                {"first_name": "Tina", "last_name": "Test", "email": "tina@example.com",
                 "contact_number": "09171234567", "profile_photo": big},
            )
        self.assertTrue(response.context["form"].has_error("profile_photo"))
