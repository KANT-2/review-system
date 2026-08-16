from django import forms
from django.contrib.auth import authenticate

from accounts.models import User


class LoginForm(forms.Form):
    """이메일 로그인 폼"""

    email = forms.EmailField(
        label="이메일",
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "name@example.com", "autofocus": True}
        ),
    )
    password = forms.CharField(
        label="비밀번호",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "비밀번호를 입력하세요"}
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")

        if email and password:
            self.user = authenticate(email=email, password=password)
            if not self.user:
                raise forms.ValidationError("이메일 또는 비밀번호가 올바르지 않습니다.")
        return cleaned_data

    def get_user(self):
        return getattr(self, "user", None)


class SignUpForm(forms.ModelForm):
    """회원가입 폼 (온보딩 항목 배제, 최소 정보 수집)"""

    password = forms.CharField(
        label="비밀번호",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "비밀번호 (6자 이상)"}
        ),
    )
    password_confirm = forms.CharField(
        label="비밀번호 확인",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "비밀번호를 한 번 더 입력하세요"}
        ),
    )

    class Meta:
        model = User
        fields = ["email"]
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "name@example.com"}
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError("비밀번호가 일치하지 않습니다.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        user.is_onboarded = False
        if commit:
            user.save()
        return user
