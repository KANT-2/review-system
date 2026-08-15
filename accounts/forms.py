from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from .models import User, WhitelistEmail

class SignUpForm(forms.ModelForm):
    """
    회원가입 폼: 화이트리스트 대조 후 자동 승인/승인 대기 분기 처리
    """
    name = forms.CharField(label='이름', max_length=30, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '홍길동'}))
    password = forms.CharField(label='비밀번호', widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '8자 이상 입력'}))

    class Meta:
        model = User
        fields = ['email', 'password', 'name']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'user@example.com'}),
        }

    def clean_password(self):
        password = self.cleaned_data.get('password')
        validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.username = self.cleaned_data['email']
        user.first_name = self.cleaned_data['name']

        # 화이트리스트 DB 대조 로직
        whitelist_entry = WhitelistEmail.objects.filter(email=user.email).first()
        if whitelist_entry:
            user.approval_status = User.ApprovalStatus.APPROVED
            user.role = whitelist_entry.role
            user.session_info = whitelist_entry.session_info
        else:
            user.approval_status = User.ApprovalStatus.PENDING

        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    """
    로그인 폼
    """
    email = forms.EmailField(label='이메일', widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'user@example.com'}))
    password = forms.CharField(label='비밀번호', widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    save_id = forms.BooleanField(required=False, label='아이디 저장')
    auto_login = forms.BooleanField(required=False, label='자동 로그인')


class OnboardingForm(forms.ModelForm):
    """
    최초 1회 필수 온보딩 폼
    """
    name = forms.CharField(label='이름', max_length=30, widget=forms.TextInput(attrs={'class': 'form-control'}))

    class Meta:
        model = User
        fields = ['name', 'session_info', 'phone']
        widgets = {
            'session_info': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 4기 풀스택 트랙'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '010-0000-0000'}),
        }