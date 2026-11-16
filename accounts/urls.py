from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/landlord/", views.dashboard_landlord, name="dashboard_landlord"),
    path("dashboard/caretaker/", views.dashboard_caretaker, name="dashboard_caretaker"),
    path("dashboard/tenant/", views.dashboard_tenant, name="dashboard_tenant"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("users/", views.user_list, name="user_list"),
    path("users/caretakers/new/", views.caretaker_create, name="caretaker_create"),
]
