from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User, canonicalize_email


class LoginForm(forms.Form):
    email = forms.EmailField(
        label="이메일", widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    password = forms.CharField(
        label="비밀번호", widget=forms.PasswordInput(attrs={"class": "form-control"})
    )

    def clean(self):
        cleaned_data = super().clean()
        email = canonicalize_email(cleaned_data.get("email"))
        password = cleaned_data.get("password")
        if email and password:
            self.user = authenticate(self.request, email=email, password=password)
            if not self.user:
                raise forms.ValidationError("이메일 또는 비밀번호가 올바르지 않습니다.")
        return cleaned_data

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

    def get_user(self):
        return getattr(self, "user", None)


class SignUpForm(forms.Form):
    email = forms.EmailField(
        label="이메일", widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    first_name = forms.CharField(
        label="이름", max_length=150, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    phone_number = forms.CharField(
        label="연락처",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )


class ConfirmationPasswordForm(forms.Form):
    password = forms.CharField(
        label="새 비밀번호",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password_confirm = forms.CharField(
        label="새 비밀번호 확인",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    def clean(self):
        data = super().clean()
        if data.get("password") != data.get("password_confirm"):
            raise forms.ValidationError("비밀번호가 일치하지 않습니다.")
        if data.get("password"):
            try:
                validate_password(data["password"])
            except ValidationError as error:
                self.add_error("password", error)
        return data


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        label="현재 비밀번호", widget=forms.PasswordInput(attrs={"class": "form-control"})
    )
    new_password = forms.CharField(
        label="새 비밀번호", widget=forms.PasswordInput(attrs={"class": "form-control"})
    )
    new_password_confirm = forms.CharField(
        label="새 비밀번호 확인", widget=forms.PasswordInput(attrs={"class": "form-control"})
    )

    def clean(self):
        data = super().clean()
        if data.get("new_password") != data.get("new_password_confirm"):
            raise forms.ValidationError("새 비밀번호가 일치하지 않습니다.")
        return data


class OnboardingForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "session_info", "phone_number"]
