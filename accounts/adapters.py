from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect

from accounts.models import User, WhitelistEmail


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """소셜 로그인 사용자 온보딩/승인 파이프라인 제어 어댑터"""

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        user.is_social_account = True
        user.is_onboarded = False  # 소셜 가입자도 승인 후 대시보드에서 온보딩을 진행하도록 설정
        extra_data = sociallogin.account.extra_data

        kakao_nickname = (
            extra_data.get("properties", {}).get("nickname")
            or extra_data.get("kakao_account", {}).get("profile", {}).get("nickname")
        )
        google_name = f"{data.get('last_name', '')}{data.get('first_name', '')}".strip() or data.get("name", "")
        full_name = kakao_nickname or google_name

        if full_name:
            user.first_name = full_name

        kakao_email = extra_data.get("kakao_account", {}).get("email")
        if kakao_email and not user.email:
            user.email = kakao_email

        return user

    def pre_social_login(self, request, sociallogin):
        extra_data = sociallogin.account.extra_data
        email = (
            sociallogin.user.email
            or extra_data.get("email")
            or extra_data.get("kakao_account", {}).get("email")
        )

        if not email:
            provider = sociallogin.account.provider
            uid = sociallogin.account.uid
            email = f"{provider}_{uid}@social.ax-eval.internal"
            sociallogin.user.email = email

        user = User.objects.filter(email=email).first()

        if user:
            if user.approval_status == User.ApprovalStatus.PENDING:
                messages.warning(request, "가입 승인 검토 중입니다. 튜터의 승인을 기다려주세요.")
                raise ImmediateHttpResponse(redirect("accounts:login"))
            elif user.approval_status == User.ApprovalStatus.REJECTED:
                messages.error(request, "승인이 거절된 계정입니다. 관리자에게 문의하세요.")
                raise ImmediateHttpResponse(redirect("accounts:login"))

            if not sociallogin.is_existing:
                sociallogin.connect(request, user)
        else:
            whitelist_entry = WhitelistEmail.objects.filter(email=email).first()
            if whitelist_entry:
                sociallogin.user.approval_status = User.ApprovalStatus.APPROVED
                sociallogin.user.role = whitelist_entry.role
                sociallogin.user.session_info = whitelist_entry.session_info
                sociallogin.user.is_onboarded = False
            else:
                sociallogin.user.approval_status = User.ApprovalStatus.PENDING
                sociallogin.user.role = User.Role.STUDENT
                sociallogin.user.is_social_account = True
                sociallogin.user.is_onboarded = False
                sociallogin.user.save()
                sociallogin.save(request)

                messages.warning(request, "신규 계정으로 가입 신청되었습니다. 튜터 승인 후 이용 가능합니다.")
                raise ImmediateHttpResponse(redirect("accounts:login"))

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        user.is_social_account = True
        user.save()
        return user

    def get_login_redirect_url(self, request):
        user = request.user
        if user.role in [User.Role.TUTOR, User.Role.ADMIN]:
            return "/accounts/tutor/dashboard/"
        return "/accounts/dashboard/"