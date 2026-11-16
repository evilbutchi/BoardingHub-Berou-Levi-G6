from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme

from .decorators import role_required
from .forms import CaretakerCreationForm, ProfileForm, RegistrationForm
from .models import User


def home(request):
    if request.user.is_authenticated:
        return redirect(request.user.get_dashboard_url())
    return redirect("accounts:login")


# ---------------------------------------------------------------- registration
def register(request):
    if request.user.is_authenticated:
        return redirect(request.user.get_dashboard_url())

    form = RegistrationForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Account created successfully. You can now log in.")
            return redirect("accounts:login")
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "accounts/register.html", {"form": form})


# ---------------------------------------------------------------- login/logout
class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        # Honor a safe ?next= (set by @login_required), else go to the role dashboard.
        next_url = self.get_redirect_url()
        if next_url:
            return next_url
        return self.request.user.get_dashboard_url()

    def get_redirect_url(self):
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return ""

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Welcome back, {form.get_user().display_name}!")
        return response

    def form_invalid(self, form):
        errors = form.non_field_errors()
        messages.error(
            self.request,
            errors[0] if errors else "Please enter your username and password.",
        )
        return super().form_invalid(form)


class LogoutView(auth_views.LogoutView):
    """POST-only logout (Django 5). Ends the session and shows a message."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.success(request, "You have been logged out.")
        return response


# ------------------------------------------------------------------ dashboards
@login_required
def dashboard(request):
    """Send each user to the dashboard for their role."""
    return redirect(request.user.get_dashboard_url())


@role_required(User.Role.LANDLORD)
def dashboard_landlord(request):
    context = {
        "tenant_count": User.objects.filter(role=User.Role.TENANT).count(),
        "caretaker_count": User.objects.filter(role=User.Role.CARETAKER).count(),
        "recent_users": User.objects.exclude(pk=request.user.pk).order_by("-date_joined")[:5],
    }
    return render(request, "accounts/dashboard_landlord.html", context)


@role_required(User.Role.CARETAKER)
def dashboard_caretaker(request):
    return render(request, "accounts/dashboard_caretaker.html")


@role_required(User.Role.TENANT)
def dashboard_tenant(request):
    return render(request, "accounts/dashboard_tenant.html")


# --------------------------------------------------------------------- profile
@login_required
def profile(request):
    # Always the logged-in user's own profile; there is no user id in the URL.
    return render(request, "accounts/profile.html", {"profile_user": request.user})


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile was updated.")
            return redirect("accounts:profile")
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "accounts/profile_edit.html", {"form": form})


# ------------------------------------------------------- landlord: manage users
@role_required(User.Role.LANDLORD)
def user_list(request):
    users = User.objects.exclude(pk=request.user.pk)
    return render(request, "accounts/user_list.html", {"users": users})


@role_required(User.Role.LANDLORD)
def caretaker_create(request):
    form = CaretakerCreationForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Caretaker account created for {user.display_name}.")
            return redirect("accounts:user_list")
        messages.error(request, "Please fix the errors below and try again.")
    return render(request, "accounts/caretaker_form.html", {"form": form})
