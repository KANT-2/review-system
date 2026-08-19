import logging
import time

from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse

from accounts.models import User, WhitelistEmail, canonicalize_email
from accounts.services import lock_canonical_email
from audit.services import record_event

security_logger = logging.getLogger("accounts.security")


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def _verified_email(self, request, sociallogin):
        provider = sociallogin.account.provider
        data = sociallogin.account.extra_data
        if provider == "google":
            nonces = request.session.get("google_oidc_nonces", {})
            nonce = data.get("nonce")
            issued_at = nonces.pop(nonce, None)
            request.session["google_oidc_nonces"] = nonces
            nonce_is_valid = issued_at is not None and time.time() - issued_at <= 300
            verified = nonce_is_valid and (
                data.get("email_verified") is True or data.get("verified_email") is True
            )
            email = data.get("email")
        elif provider == "kakao":
            account = data.get("kakao_account", {})
            verified = (
                account.get("has_email") is True
                and account.get("email_needs_agreement") is False
                and account.get("is_email_valid") is True
                and account.get("is_email_verified") is True
            )
            email = account.get("email")
        else:
            return None
        return canonicalize_email(email) if verified and email else None

    def pre_social_login(self, request, sociallogin):
        verified_email = self._verified_email(request, sociallogin)
        if not verified_email:
            messages.error(request, "공급자가 확인한 이메일이 없어 로그인할 수 없습니다.")
            raise ImmediateHttpResponse(redirect("accounts:login"))

        with transaction.atomic():
            lock_canonical_email(verified_email)
            if sociallogin.is_existing:
                user = User.objects.select_for_update().get(pk=sociallogin.user.pk)
                if canonicalize_email(user.email) != verified_email:
                    user.email_needs_review = True
                    user.save(update_fields=["email_needs_review"])
                    security_logger.warning("social_email_changed")
                if not user.is_active or user.approval_status != User.ApprovalStatus.APPROVED:
                    messages.warning(
                        request, "승인되었거나 활성 상태인 계정만 로그인할 수 있습니다."
                    )
                    raise ImmediateHttpResponse(redirect("accounts:login"))
                return

            user = User.objects.select_for_update().filter(email=verified_email).first()
            whitelist = (
                WhitelistEmail.objects.select_for_update().filter(email=verified_email).first()
            )
            created = user is None
            if created:
                user = User.objects.create_user(
                    email=verified_email,
                    password=None,
                    _email_verified=True,
                    first_name=(sociallogin.user.first_name or "")[:150],
                    role=User.Role.STUDENT,
                    is_social_account=True,
                    approval_status=(
                        User.ApprovalStatus.APPROVED if whitelist else User.ApprovalStatus.PENDING
                    ),
                    session_info=whitelist.session_info if whitelist else "",
                    # 소셜 가입자도 승인 뒤 온보딩에서 이름·기수·연락처를 직접 채운다.
                    is_onboarded=False,
                )
            sociallogin.connect(request, user)
            # AUD-001: 소셜 계정 최초 연결을 남긴다. AUD-002에 따라 code·token·state·nonce는
            # 기록하지 않고 공급자 이름과 계정 생성 여부만 남긴다.
            record_event(
                action="SOCIAL_ACCOUNT_LINKED",
                target=user,
                actor=user,
                summary={
                    "provider": sociallogin.account.provider,
                    "account_created": created,
                    "approval_status": user.approval_status,
                },
            )
            if user.approval_status != User.ApprovalStatus.APPROVED:
                messages.warning(request, "가입 신청이 접수되었습니다. 튜터 승인을 기다려주세요.")
                raise ImmediateHttpResponse(redirect("accounts:login"))

    def save_user(self, request, sociallogin, form=None):
        if sociallogin.user.pk:
            return sociallogin.user
        return super().save_user(request, sociallogin, form)

    def get_login_redirect_url(self, request):
        user = request.user
        request.session["auth_session_version"] = user.auth_session_version
        request.session.set_expiry(60 * 60 * 24 * 14)
        if user.role in {User.Role.TUTOR, User.Role.ADMIN}:
            return reverse("accounts:account_admin")
        return reverse("accounts:dashboard")
