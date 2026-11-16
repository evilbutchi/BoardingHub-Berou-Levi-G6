from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User

MAX_PHOTO_BYTES = 2 * 1024 * 1024  # 2 MB


class EmailUniquenessMixin:
    """Case-insensitive unique email check (excludes the current instance)."""

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class RegistrationForm(EmailUniquenessMixin, UserCreationForm):
    """Public sign-up. New accounts are always Tenants."""

    role = User.Role.TENANT

    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    contact_number = forms.CharField(
        max_length=20,
        required=True,
        validators=User._meta.get_field("contact_number").validators,
        help_text="Digits, spaces or dashes. May start with +.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "username", "email", "contact_number")

    def clean_username(self):
        username = super().clean_username()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.role
        if commit:
            user.save()
        return user


class CaretakerCreationForm(RegistrationForm):
    """Used by the Landlord to create Caretaker accounts."""

    role = User.Role.CARETAKER


class ProfileForm(EmailUniquenessMixin, forms.ModelForm):
    contact_number = forms.CharField(
        max_length=20,
        required=True,
        validators=User._meta.get_field("contact_number").validators,
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "contact_number", "profile_photo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["email"].required = True
        self.fields["profile_photo"].widget.attrs["accept"] = "image/*"

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")
        # Only newly uploaded files have a size attribute we need to check.
        if photo and hasattr(photo, "size") and photo.size > MAX_PHOTO_BYTES:
            raise forms.ValidationError("Photo must be 2 MB or smaller.")
        return photo
