from django import forms
from django.conf import settings
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
    """가입 신청은 이메일과 비밀번호만 받는다.

    확인 메일을 보낼 수 없는 환경이라(발신 도메인 PTR 미설정) 이메일 소유 확인 단계 없이
    바로 계정을 만든다. 명단(WhitelistEmail)에 없는 계정은 튜터 승인을 기다린다.

    이름·연락처는 승인 뒤 온보딩(OnboardingForm)에서 본인이 직접 입력한다 -
    승인 전에 개인정보를 미리 받아두지 않는다.
    """

    email = forms.EmailField(
        label="이메일", widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    password = forms.CharField(
        label="비밀번호",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password_confirm = forms.CharField(
        label="비밀번호 확인",
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
    """승인된 수강생이 평가에 참여하기 전에 한 번 채우는 필수 프로필.

    가입 신청에서는 이메일만 받으므로(SignUpForm) 이름·연락처는 여기서 본인이 입력한다.
    """

    class Meta:
        model = User
        fields = ["first_name", "phone_number"]
        labels = {
            "first_name": "이름",
            "phone_number": "연락처",
        }
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "실명을 입력해 주세요"}
            ),
            "phone_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "010-0000-0000"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True


def clean_profile_image(uploaded_file):
    """마이페이지에서 올린 프로필 사진을 검사한다.

    ``forms.ImageField``가 Pillow로 실제 이미지인지 확인하므로 확장자만 바꾼 파일은 걸린다.
    용량 상한은 화면(accept 속성)만으로 막을 수 없어 서버에서 다시 본다.

    문제가 있으면 ``ValidationError``를 올린다.
    """
    image = forms.ImageField().clean(uploaded_file)
    if image.size > settings.PROFILE_IMAGE_MAX_BYTES:
        limit_mb = settings.PROFILE_IMAGE_MAX_BYTES // (1024 * 1024)
        raise ValidationError(f"사진은 {limit_mb}MB 이하만 올릴 수 있습니다.")
    return image


class WhitelistEntryForm(forms.Form):
    """수강생 명단 등록 - 여러 줄 붙여넣기를 그대로 받는다(한 줄에 이메일 하나)."""

    emails = forms.CharField(
        label="이메일",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "student1@ax.com\nstudent2@ax.com",
            }
        ),
        help_text="한 줄에 하나씩 붙여넣으면 한 번에 등록됩니다.",
    )

    def clean_emails(self):
        raw = self.cleaned_data["emails"].replace(",", "\n")
        field = forms.EmailField()
        seen, invalid = [], []
        for line in raw.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            try:
                field.clean(candidate)
            except ValidationError:
                invalid.append(candidate)
                continue
            canonical = canonicalize_email(candidate)
            if canonical not in seen:
                seen.append(canonical)
        if invalid:
            raise ValidationError(f"이메일 형식이 아닌 항목이 있습니다: {', '.join(invalid[:3])}")
        if not seen:
            raise ValidationError("등록할 이메일을 한 개 이상 입력해 주세요.")
        return seen
