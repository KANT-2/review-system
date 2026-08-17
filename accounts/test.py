import json
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.conf import settings
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.adapters import CustomSocialAccountAdapter
from accounts.middleware import TrustedProxyMiddleware
from accounts.models import User, WhitelistEmail
from accounts.services import InvalidAccountTransition, set_account_active

STRONG_PASSWORD = "Correct-Horse-Battery-2026!"
NEW_STRONG_PASSWORD = "Another-Correct-Battery-2026!"


class AccountsTests(TestCase):
    def setUp(self):
        self.approved_student = User.objects.create_user(
            email="student@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            first_name="홍길동",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.tutor_user = User.objects.create_user(
            email="tutor@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            first_name="김튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.whitelist_entry = WhitelistEmail.objects.create(
            email="whitelist@ax.com",
            session_info="2기",
        )

    def _signup(self, email):
        return self.client.post(
            reverse("accounts:api_signup"),
            data=json.dumps(
                {"email": email, "first_name": "신규", "phone_number": "010-3333-4444"}
            ),
            content_type="application/json",
        )

    def _confirm(self, user):
        address = EmailAddress.objects.get(user=user, primary=True)
        key = EmailConfirmationHMAC.create(address).key
        self.client.get(reverse("accounts:email_confirm_key", kwargs={"key": key}))
        return self.client.post(
            reverse("accounts:email_confirm"),
            {"password": STRONG_PASSWORD, "password_confirm": STRONG_PASSWORD},
        )

    def test_whitelist_requires_ownership_before_auto_approval(self):
        response = self._signup("Whitelist@AX.com")
        self.assertEqual(response.status_code, 202)
        user = User.objects.get(email="whitelist@ax.com")
        self.assertEqual(user.approval_status, User.ApprovalStatus.PENDING)
        self.assertFalse(user.has_usable_password())

        response = self._confirm(user)

        self.assertRedirects(response, reverse("accounts:login"))
        user.refresh_from_db()
        self.assertEqual(user.approval_status, User.ApprovalStatus.APPROVED)
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertTrue(EmailAddress.objects.get(user=user).verified)

    def test_non_whitelist_remains_pending_after_confirmation(self):
        self._signup("newbie@ax.com")
        user = User.objects.get(email="newbie@ax.com")

        self._confirm(user)

        user.refresh_from_db()
        self.assertEqual(user.approval_status, User.ApprovalStatus.PENDING)

    def test_signup_returns_generic_response_for_existing_email(self):
        response = self._signup("STUDENT@ax.com")

        self.assertEqual(response.status_code, 202)
        self.assertNotContains(response, "이미 가입", status_code=202)
        self.assertEqual(User.objects.filter(email="student@ax.com").count(), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_signup_sends_korean_confirmation_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._signup("mail-check@ax.com")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("이메일 주소를 확인해 주세요", mail.outbox[0].subject)
        self.assertIn("/accounts/email/confirm/", mail.outbox[0].body)

    def test_signup_rate_limit_returns_retry_after(self):
        for index in range(5):
            response = self._signup(f"rate-{index}@ax.com")
            self.assertEqual(response.status_code, 202)

        response = self._signup("rate-blocked@ax.com")

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

    def test_login_requires_verified_approved_account(self):
        pending = User.objects.create_user(
            email="pending@ax.com",
            password=STRONG_PASSWORD,
            approval_status=User.ApprovalStatus.PENDING,
        )
        EmailAddress.objects.filter(user=pending).update(verified=True)

        response = self.client.post(
            reverse("accounts:login"),
            {"email": pending.email, "password": STRONG_PASSWORD},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_session_expiry_follows_remember_choice(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "email": self.approved_student.email,
                "password": STRONG_PASSWORD,
                "remember_session": "on",
            },
        )

        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertGreater(self.client.session.get_expiry_age(), 60 * 60 * 24 * 13)

    def test_login_keeps_signup_as_modal_and_signup_url_opens_it(self):
        login = self.client.get(reverse("accounts:login"))
        signup = self.client.get(reverse("accounts:signup"))

        self.assertContains(login, 'id="signupModal"')
        self.assertContains(login, f'action="{reverse("accounts:signup")}"')
        self.assertRedirects(signup, f"{reverse('accounts:login')}?signup=1")

    def test_invalid_signup_is_rendered_back_inside_modal(self):
        response = self.client.post(reverse("accounts:signup"), {"email": "invalid"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="signupModal"')
        self.assertContains(response, "올바른 이메일 주소를 입력하세요")

    def test_student_home_uses_explicit_empty_state_without_active_round(self):
        self.client.force_login(self.approved_student)

        home = self.client.get(reverse("home"))
        dashboard = self.client.get(reverse("accounts:dashboard"))
        mypage = self.client.get(reverse("accounts:mypage"))

        self.assertRedirects(home, reverse("accounts:dashboard"))
        self.assertContains(dashboard, "현재 진행 중인 평가 회차가 없습니다")
        self.assertNotContains(dashboard, "DEMO")
        self.assertNotContains(dashboard, "데이터 연결 준비 중")
        self.assertContains(mypage, "공개된 평가 결과가 없습니다")

    def test_student_pages_use_business_empty_states_without_demo_data(self):
        self.client.force_login(self.approved_student)

        dashboard = self.client.get(reverse("accounts:dashboard"))
        mypage = self.client.get(reverse("accounts:mypage"))

        self.assertContains(dashboard, "현재 진행 중인 평가 회차가 없습니다")
        self.assertContains(mypage, "공개된 평가 결과가 없습니다")
        self.assertNotContains(dashboard, "데이터 연결 준비 중")

    def test_login_is_locked_after_five_failures(self):
        for _ in range(5):
            self.client.post(
                reverse("accounts:login"),
                {"email": self.approved_student.email, "password": "wrong-password"},
            )

        response = self.client.post(
            reverse("accounts:login"),
            {"email": self.approved_student.email, "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "900")

    def test_tutor_can_approve_only_verified_pending_student(self):
        target = User.objects.create_user(
            email="target@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            approval_status=User.ApprovalStatus.PENDING,
        )
        self.client.force_login(self.tutor_user)

        response = self.client.post(
            reverse("accounts:api_approve_user", kwargs={"user_id": target.id})
        )

        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.approval_status, User.ApprovalStatus.APPROVED)

    def test_duplicate_approval_is_conflict(self):
        target = User.objects.create_user(
            email="target2@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            approval_status=User.ApprovalStatus.PENDING,
        )
        self.client.force_login(self.tutor_user)
        url = reverse("accounts:api_approve_user", kwargs={"user_id": target.id})
        self.client.post(url)

        response = self.client.post(url)

        self.assertEqual(response.status_code, 409)

    def test_student_cannot_approve_user(self):
        target = User.objects.create_user(
            email="target3@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            approval_status=User.ApprovalStatus.PENDING,
        )
        self.client.force_login(self.approved_student)

        response = self.client.post(
            reverse("accounts:api_approve_user", kwargs={"user_id": target.id})
        )

        self.assertEqual(response.status_code, 403)

    def test_profile_update_accepts_json_and_rejects_invalid_json(self):
        self.client.force_login(self.approved_student)
        url = reverse("accounts:api_update_profile")
        invalid = self.client.post(url, data="{", content_type="application/json")
        valid = self.client.post(
            url,
            data=json.dumps({"first_name": "김수정", "phone_number": "010-8888-7777"}),
            content_type="application/json",
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(valid.status_code, 200)
        self.approved_student.refresh_from_db()
        self.assertEqual(self.approved_student.first_name, "김수정")

    def test_password_change_checks_current_password_and_keeps_session(self):
        self.client.force_login(self.approved_student)
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "current_password": STRONG_PASSWORD,
                "new_password": NEW_STRONG_PASSWORD,
                "new_password_confirm": NEW_STRONG_PASSWORD,
            },
        )

        self.assertRedirects(response, reverse("accounts:mypage"))
        self.approved_student.refresh_from_db()
        self.assertTrue(self.approved_student.check_password(NEW_STRONG_PASSWORD))
        self.assertIn("_auth_user_id", self.client.session)

    def test_legacy_password_rotation_restricts_other_pages(self):
        self.approved_student.must_rotate_password = True
        self.approved_student.save(update_fields=["must_rotate_password"])
        self.client.force_login(self.approved_student)

        dashboard = self.client.get(reverse("accounts:dashboard"))
        change_page = self.client.get(reverse("accounts:password_change"))

        self.assertRedirects(dashboard, reverse("accounts:password_change"))
        self.assertEqual(change_page.status_code, 200)

    def test_logout_is_post_only(self):
        self.client.force_login(self.approved_student)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertRedirects(
            self.client.post(reverse("accounts:logout")), reverse("accounts:login")
        )

    def test_student_logout_is_available_from_profile_menu(self):
        self.client.force_login(self.approved_student)

        response = self.client.get(reverse("accounts:mypage"))

        self.assertContains(response, 'id="user-profile-menu-button"')
        self.assertContains(response, f'action="{reverse("accounts:logout")}"')
        self.assertContains(response, "로그아웃")

    def test_tutor_logout_is_available_from_profile_menu(self):
        self.client.force_login(self.tutor_user)

        response = self.client.get(reverse("accounts:tutor_dashboard"))

        self.assertContains(response, 'id="tutor-profile-menu-button"')
        self.assertContains(response, f'action="{reverse("accounts:logout")}"')
        self.assertContains(response, "로그아웃")

    def test_unsafe_reset_and_allauth_account_routes_are_closed(self):
        closed_paths = [
            "/accounts/api/password/verify/",
            "/accounts/api/password/reset/",
            "/accounts/password/reset/",
            "/accounts/email/",
            "/accounts/social/connections/",
        ]
        for path in closed_paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_social_login_start_is_post_only(self):
        self.assertEqual(self.client.get(reverse("google_login")).status_code, 405)
        self.assertEqual(self.client.get(reverse("kakao_login")).status_code, 405)

    @override_settings(GOOGLE_OAUTH_ENABLED=False, KAKAO_OAUTH_ENABLED=False)
    def test_unconfigured_social_login_endpoints_are_closed(self):
        self.assertEqual(self.client.post(reverse("google_login")).status_code, 404)
        self.assertEqual(self.client.post(reverse("kakao_login")).status_code, 404)

    @override_settings(
        GOOGLE_OAUTH_ENABLED=True,
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "APPS": [
                    {
                        "client_id": "google-test-client",
                        "secret": "google-test-secret",
                        "key": "",
                    }
                ],
                "SCOPE": ["openid", "email", "profile"],
                "AUTH_PARAMS": {"access_type": "online"},
                "OAUTH_PKCE_ENABLED": True,
            }
        },
    )
    def test_configured_google_login_builds_hardened_authorization_redirect(self):
        response = self.client.post(reverse("google_login"))

        query = parse_qs(urlparse(response["Location"]).query)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response["Location"]).netloc, "accounts.google.com")
        self.assertEqual(query["client_id"], ["google-test-client"])
        self.assertIn("state", query)
        self.assertIn("nonce", query)
        self.assertIn("code_challenge", query)
        self.assertEqual(query["code_challenge_method"], ["S256"])

    @override_settings(
        KAKAO_OAUTH_ENABLED=True,
        SOCIALACCOUNT_PROVIDERS={
            "kakao": {
                "APPS": [
                    {
                        "client_id": "kakao-test-client",
                        "secret": "kakao-test-secret",
                        "key": "",
                    }
                ]
            }
        },
    )
    def test_configured_kakao_login_builds_authorization_redirect(self):
        response = self.client.post(reverse("kakao_login"))

        query = parse_qs(urlparse(response["Location"]).query)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response["Location"]).netloc, "kauth.kakao.com")
        self.assertEqual(query["client_id"], ["kakao-test-client"])
        self.assertIn("state", query)

    @override_settings(GOOGLE_OAUTH_ENABLED=True)
    def test_expired_oauth_state_is_rejected_before_callback(self):
        session = self.client.session
        session["socialaccount_states"] = {"expired": ({}, time.time() - 301)}
        session.save()

        response = self.client.get(reverse("google_callback"), {"state": "expired"})

        self.assertEqual(response.status_code, 400)

    def test_allauth_token_storage_is_disabled(self):
        self.assertFalse(settings.SOCIALACCOUNT_STORE_TOKENS)


class CsrfProtectionTests(TestCase):
    def test_signup_rejects_missing_csrf_when_enforced(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("accounts:api_signup"),
            data=json.dumps({"email": "csrf@ax.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class TrustedProxyTests(TestCase):
    @override_settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_IPS=["172.30.0.0/24"],
        TRUSTED_PROXY_HOPS=1,
    )
    def test_single_trusted_proxy_uses_forwarded_client_ip_and_https(self):
        request = SimpleNamespace(
            META={
                "REMOTE_ADDR": "172.30.0.3",
                "HTTP_X_FORWARDED_FOR": "203.0.113.10",
                "HTTP_X_FORWARDED_PROTO": "https",
                "wsgi.url_scheme": "http",
            }
        )

        response = TrustedProxyMiddleware(lambda current: current)(request)

        self.assertEqual(response.META["REMOTE_ADDR"], "203.0.113.10")
        self.assertEqual(response.META["wsgi.url_scheme"], "https")

    @override_settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_IPS=["172.30.0.0/24"],
        TRUSTED_PROXY_HOPS=1,
    )
    def test_untrusted_source_cannot_spoof_forwarded_headers(self):
        request = SimpleNamespace(
            META={
                "REMOTE_ADDR": "203.0.113.20",
                "HTTP_X_FORWARDED_FOR": "198.51.100.99",
                "HTTP_X_FORWARDED_PROTO": "https",
                "wsgi.url_scheme": "http",
            }
        )

        response = TrustedProxyMiddleware(lambda current: current)(request)

        self.assertEqual(response.META["REMOTE_ADDR"], "203.0.113.20")
        self.assertNotIn("HTTP_X_FORWARDED_FOR", response.META)
        self.assertNotIn("HTTP_X_FORWARDED_PROTO", response.META)
        self.assertEqual(response.META["wsgi.url_scheme"], "http")


class SocialClaimTests(TestCase):
    def test_google_requires_verified_email_and_matching_nonce(self):
        nonce = "one-time-nonce"
        request = SimpleNamespace(session={"google_oidc_nonces": {nonce: time.time()}})
        sociallogin = SimpleNamespace(
            account=SimpleNamespace(
                provider="google",
                extra_data={
                    "email": "Google@Example.com",
                    "email_verified": True,
                    "nonce": nonce,
                },
            )
        )

        email = CustomSocialAccountAdapter()._verified_email(request, sociallogin)

        self.assertEqual(email, "google@example.com")
        self.assertNotIn(nonce, request.session["google_oidc_nonces"])

    def test_kakao_requires_every_email_verification_flag(self):
        request = SimpleNamespace(session={})
        sociallogin = SimpleNamespace(
            account=SimpleNamespace(
                provider="kakao",
                extra_data={
                    "kakao_account": {
                        "email": "Kakao@Example.com",
                        "has_email": True,
                        "email_needs_agreement": False,
                        "is_email_valid": True,
                        "is_email_verified": False,
                    }
                },
            )
        )

        email = CustomSocialAccountAdapter()._verified_email(request, sociallogin)

        self.assertIsNone(email)


class AuthorityConstraintTests(TransactionTestCase):
    def test_admin_role_requires_staff_flag(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                email="invalid-admin@ax.com",
                password=STRONG_PASSWORD,
                role=User.Role.ADMIN,
                is_staff=False,
            )

    def test_email_is_immutable(self):
        user = User.objects.create_user(email="immutable@ax.com", password=STRONG_PASSWORD)
        user.email = "changed@ax.com"
        with self.assertRaises(ValueError):
            user.save()

    def test_suspension_invalidates_existing_session_version(self):
        admin = User.objects.create_superuser(
            email="admin@ax.com", password=STRONG_PASSWORD, _email_verified=True
        )
        target = User.objects.create_user(
            email="suspended@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        old_version = target.auth_session_version

        target = set_account_active(actor=admin, target_id=target.pk, is_active=False)

        self.assertFalse(target.is_active)
        self.assertGreater(target.auth_session_version, old_version)

    def test_two_superusers_cannot_suspend_each_other_concurrently(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL advisory-lock behavior")
        first = User.objects.create_superuser(
            email="first-admin@ax.com", password=STRONG_PASSWORD, _email_verified=True
        )
        second = User.objects.create_superuser(
            email="second-admin@ax.com", password=STRONG_PASSWORD, _email_verified=True
        )
        barrier = threading.Barrier(2)
        outcomes = []

        def suspend(actor_id, target_id):
            connections.close_all()
            actor = User.objects.get(pk=actor_id)
            barrier.wait()
            try:
                set_account_active(actor=actor, target_id=target_id, is_active=False)
            except (InvalidAccountTransition, PermissionDenied):
                outcomes.append("blocked")
            else:
                outcomes.append("suspended")
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=suspend, args=(first.pk, second.pk)),
            threading.Thread(target=suspend, args=(second.pk, first.pk)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(outcomes, ["suspended", "blocked"])
        self.assertEqual(User.objects.filter(is_superuser=True, is_active=True).count(), 1)
