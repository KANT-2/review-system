from django import forms
from django.contrib.auth import authenticate

from accounts.models import User


class LoginForm(forms.Form):
    """일반 이메일 로그인 폼"""

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
    """일반 수강생 회원가입 폼"""

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
        fields = ["email", "first_name", "phone_number"]
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "name@example.com"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "실명을 입력하세요"}
            ),
            "phone_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "010-1234-5678"}
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
        if commit:
            user.save()
        return user


class OnboardingForm(forms.ModelForm):
    """최초 로그인 수강생 온보딩 폼"""

    class Meta:
        model = User
        fields = ["first_name", "session_info", "phone_number"]
        labels = {
            "first_name": "이름(실명)",
            "session_info": "기수 정보",
            "phone_number": "연락처",
        }
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "홍길동", "required": True}
            ),
            "session_info": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "예: 2기 / 평일반", "required": True}
            ),
            "phone_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "010-0000-0000", "required": True}
            ),
        }
