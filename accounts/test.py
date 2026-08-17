import json
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from allauth.account.models import EmailAddress
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
            is_onboarded=True,
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

    def _signup(self, email, password=STRONG_PASSWORD):
        return self.client.post(
            reverse("accounts:api_signup"),
            data=json.dumps({"email": email, "password": password, "password_confirm": password}),
            content_type="application/json",
        )

    def test_whitelisted_email_is_approved_right_after_signup(self):
        """명단에 있는 주소는 확인 메일 없이 바로 로그인할 수 있어야 한다."""
        response = self._signup("Whitelist@AX.com")

        self.assertEqual(response.status_code, 202)
        user = User.objects.get(email="whitelist@ax.com")
        self.assertEqual(user.approval_status, User.ApprovalStatus.APPROVED)
        self.assertEqual(user.session_info, "2기")
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertTrue(EmailAddress.objects.get(user=user).verified)

    def test_non_whitelist_signup_waits_for_tutor_approval(self):
        self._signup("newbie@ax.com")

        user = User.objects.get(email="newbie@ax.com")
        self.assertEqual(user.approval_status, User.ApprovalStatus.PENDING)
        self.assertTrue(user.check_password(STRONG_PASSWORD))

    def test_signup_returns_generic_response_for_existing_email(self):
        response = self._signup("STUDENT@ax.com")

        self.assertEqual(response.status_code, 202)
        self.assertNotContains(response, "이미 가입", status_code=202)
        self.assertEqual(User.objects.filter(email="student@ax.com").count(), 1)
        # 기존 계정의 비밀번호가 덮이면 안 된다.
        self.approved_student.refresh_from_db()
        self.assertTrue(self.approved_student.check_password(STRONG_PASSWORD))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_signup_does_not_send_any_email(self):
        """발신 도메인 PTR을 설정할 수 없어 확인 메일 단계를 두지 않는다."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self._signup("mail-check@ax.com")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 0)

    def test_signup_rejects_weak_password(self):
        response = self._signup("weak-password@ax.com", password="1234")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="weak-password@ax.com").exists())

    def test_signup_rate_limit_returns_retry_after(self):
        for index in range(5):
            response = self._signup(f"rate-{index}@ax.com")
            self.assertEqual(response.status_code, 202)

        response = self._signup("rate-blocked@ax.com")

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

    def test_login_requires_approved_account(self):
        pending = User.objects.create_user(
            email="pending@ax.com",
            password=STRONG_PASSWORD,
            approval_status=User.ApprovalStatus.PENDING,
        )

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

    def test_signup_form_asks_for_email_and_password_only(self):
        """가입 신청은 계정 정보만 받는다 - 개인정보는 승인 뒤 온보딩에서 받는다."""
        page = self.client.get(reverse("accounts:login"), {"signup": "1"})

        self.assertEqual(
            list(page.context["signup_form"].fields),
            ["email", "password", "password_confirm"],
        )
        self.assertNotContains(page, 'name="phone_number"')

    def test_signup_stores_no_personal_details(self):
        self._signup("email-only@ax.com")

        user = User.objects.get(email="email-only@ax.com")
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.phone_number, "")
        self.assertFalse(user.is_onboarded)

    def test_student_without_profile_is_sent_to_onboarding(self):
        rookie = User.objects.create_user(
            email="rookie@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(rookie)

        dashboard = self.client.get(reverse("accounts:dashboard"))
        mypage = self.client.get(reverse("accounts:mypage"))

        self.assertRedirects(dashboard, reverse("accounts:onboarding"))
        self.assertRedirects(mypage, reverse("accounts:onboarding"))

    def test_onboarding_saves_profile_and_unlocks_dashboard(self):
        rookie = User.objects.create_user(
            email="rookie2@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(rookie)

        response = self.client.post(
            reverse("accounts:onboarding"),
            {
                "first_name": " 김민준 ",
                "session_info": "5기 풀스택",
                "phone_number": "010-1111-2222",
            },
        )

        self.assertRedirects(response, reverse("accounts:dashboard"))
        rookie.refresh_from_db()
        self.assertEqual(rookie.first_name, "김민준")
        self.assertEqual(rookie.session_info, "5기 풀스택")
        self.assertEqual(rookie.phone_number, "010-1111-2222")
        self.assertTrue(rookie.is_onboarded)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)

    def test_onboarding_requires_every_field(self):
        rookie = User.objects.create_user(
            email="rookie3@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(rookie)

        response = self.client.post(
            reverse("accounts:onboarding"),
            {"first_name": "김민준", "session_info": "", "phone_number": ""},
        )

        self.assertEqual(response.status_code, 200)
        rookie.refresh_from_db()
        self.assertFalse(rookie.is_onboarded)

    def test_onboarded_student_is_not_sent_back_to_onboarding(self):
        self.client.force_login(self.approved_student)

        response = self.client.get(reverse("accounts:onboarding"))

        self.assertRedirects(response, reverse("accounts:dashboard"))

    def test_onboarding_gate_is_enforced_on_the_server(self):
        """화면에서 가리는 방식이 아니라 서버가 되돌려 보내야 한다."""
        rookie = User.objects.create_user(
            email="rookie4@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(rookie)

        dashboard = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(dashboard.status_code, 302)
        self.assertNotContains(
            self.client.get(reverse("accounts:onboarding")), 'id="onboardingModal"'
        )

    def test_layout_offers_a_dark_mode_toggle(self):
        self.client.force_login(self.approved_student)

        dashboard = self.client.get(reverse("accounts:dashboard"))
        login_page = Client().get(reverse("accounts:login"))

        self.assertContains(dashboard, 'id="axThemeToggle"')
        self.assertContains(dashboard, "ax_theme")
        self.assertContains(login_page, 'id="axThemeToggle"')

    def test_tutor_registers_multiple_whitelist_emails_at_once(self):
        """명단 붙여넣기 - 운영자가 admin 없이 자동 승인 대상을 등록할 수 있어야 한다."""
        self.client.force_login(self.tutor_user)

        response = self.client.post(
            reverse("accounts:whitelist"),
            {
                "emails": "First@AX.com\nsecond@ax.com, third@ax.com\n\n",
                "session_info": "5기 풀스택",
            },
        )

        self.assertRedirects(response, reverse("accounts:whitelist"))
        registered = set(WhitelistEmail.objects.values_list("email", flat=True))
        self.assertTrue({"first@ax.com", "second@ax.com", "third@ax.com"} <= registered)
        self.assertEqual(
            WhitelistEmail.objects.get(email="first@ax.com").session_info, "5기 풀스택"
        )

    def test_registering_an_existing_email_updates_the_session_only(self):
        self.client.force_login(self.tutor_user)

        self.client.post(
            reverse("accounts:whitelist"),
            {"emails": self.whitelist_entry.email, "session_info": "3기"},
        )

        self.assertEqual(WhitelistEmail.objects.filter(email=self.whitelist_entry.email).count(), 1)
        self.whitelist_entry.refresh_from_db()
        self.assertEqual(self.whitelist_entry.session_info, "3기")

    def test_invalid_email_is_rejected_without_saving_anything(self):
        self.client.force_login(self.tutor_user)
        before = WhitelistEmail.objects.count()

        response = self.client.post(
            reverse("accounts:whitelist"), {"emails": "ok@ax.com\n엉망진창", "session_info": ""}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(WhitelistEmail.objects.count(), before)

    def test_whitelist_screen_shows_whether_each_email_signed_up(self):
        WhitelistEmail.objects.create(email=self.approved_student.email, session_info="1기")
        self.client.force_login(self.tutor_user)

        response = self.client.get(reverse("accounts:whitelist"))

        rows = {entry.email: entry.account for entry in response.context["entries"]}
        self.assertEqual(rows[self.approved_student.email], self.approved_student)
        self.assertIsNone(rows[self.whitelist_entry.email])

    def test_tutor_removes_whitelist_email(self):
        self.client.force_login(self.tutor_user)

        response = self.client.post(
            reverse("accounts:whitelist_delete", args=[self.whitelist_entry.pk])
        )

        self.assertRedirects(response, reverse("accounts:whitelist"))
        self.assertFalse(WhitelistEmail.objects.filter(pk=self.whitelist_entry.pk).exists())

    def test_students_cannot_touch_the_whitelist(self):
        self.client.force_login(self.approved_student)

        listing = self.client.get(reverse("accounts:whitelist"))
        removal = self.client.post(
            reverse("accounts:whitelist_delete", args=[self.whitelist_entry.pk])
        )

        self.assertEqual(listing.status_code, 403)
        self.assertEqual(removal.status_code, 403)
        self.assertTrue(WhitelistEmail.objects.filter(pk=self.whitelist_entry.pk).exists())

    def test_account_screen_lists_and_filters_accounts(self):
        self.client.force_login(self.tutor_user)

        listing = self.client.get(reverse("accounts:account_admin"))
        students_only = self.client.get(reverse("accounts:account_admin"), {"role": "student"})
        searched = self.client.get(reverse("accounts:account_admin"), {"q": "홍길동"})

        self.assertContains(listing, self.approved_student.email)
        self.assertContains(listing, self.tutor_user.email)
        self.assertNotIn(self.tutor_user, students_only.context["accounts"])
        self.assertIn(self.approved_student, searched.context["accounts"])

    def test_rejected_account_can_be_moved_back_to_pending(self):
        rejected = User.objects.create_user(
            email="rejected@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.REJECTED,
        )
        self.client.force_login(self.tutor_user)

        response = self.client.post(
            reverse("accounts:account_action", args=[rejected.pk, "revert-approval"])
        )

        self.assertRedirects(response, reverse("accounts:account_admin"))
        rejected.refresh_from_db()
        self.assertEqual(rejected.approval_status, User.ApprovalStatus.PENDING)

    def test_tutor_requires_password_reset_for_a_student(self):
        self.client.force_login(self.tutor_user)

        self.client.post(
            reverse(
                "accounts:account_action", args=[self.approved_student.pk, "require-password-reset"]
            )
        )

        self.approved_student.refresh_from_db()
        self.assertTrue(self.approved_student.must_rotate_password)

    def test_tutor_cannot_deactivate_or_change_roles(self):
        """계정 비활성화와 역할 변경은 관리자만 - 튜터에게는 버튼도 보이지 않는다."""
        self.client.force_login(self.tutor_user)

        page = self.client.get(reverse("accounts:account_admin"))
        deactivate = self.client.post(
            reverse("accounts:account_action", args=[self.approved_student.pk, "deactivate"])
        )
        promote = self.client.post(
            reverse("accounts:account_action", args=[self.approved_student.pk, "make-tutor"])
        )

        self.assertFalse(page.context["can_change_role"])
        self.assertContains(page, "관리자만 할 수 있습니다")
        self.approved_student.refresh_from_db()
        self.assertTrue(self.approved_student.is_active)
        self.assertEqual(self.approved_student.role, User.Role.STUDENT)
        self.assertRedirects(deactivate, reverse("accounts:account_admin"))
        self.assertRedirects(promote, reverse("accounts:account_admin"))

    def test_admin_deactivates_account_and_ends_its_sessions(self):
        admin = User.objects.create_superuser(
            email="ops-admin@ax.com", password=STRONG_PASSWORD, first_name="관리자"
        )
        before = self.approved_student.auth_session_version
        self.client.force_login(admin)

        self.client.post(
            reverse("accounts:account_action", args=[self.approved_student.pk, "deactivate"])
        )

        self.approved_student.refresh_from_db()
        self.assertFalse(self.approved_student.is_active)
        self.assertGreater(self.approved_student.auth_session_version, before)

    def test_admin_switches_role_between_student_and_tutor(self):
        admin = User.objects.create_superuser(
            email="role-admin@ax.com", password=STRONG_PASSWORD, first_name="관리자"
        )
        self.client.force_login(admin)

        self.client.post(
            reverse("accounts:account_action", args=[self.approved_student.pk, "make-tutor"])
        )
        self.approved_student.refresh_from_db()
        self.assertEqual(self.approved_student.role, User.Role.TUTOR)

        self.client.post(
            reverse("accounts:account_action", args=[self.approved_student.pk, "make-student"])
        )
        self.approved_student.refresh_from_db()
        self.assertEqual(self.approved_student.role, User.Role.STUDENT)

    def test_students_cannot_reach_account_management(self):
        self.client.force_login(self.approved_student)

        listing = self.client.get(reverse("accounts:account_admin"))
        action = self.client.post(
            reverse("accounts:account_action", args=[self.tutor_user.pk, "deactivate"])
        )

        self.assertEqual(listing.status_code, 403)
        self.assertEqual(action.status_code, 403)

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

    def test_tutor_can_approve_a_pending_student(self):
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

    def test_allauth_account_routes_are_closed(self):
        closed_paths = [
            "/accounts/password/reset/",
            "/accounts/email/",
            "/accounts/social/connections/",
        ]
        for path in closed_paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_password_reset_endpoints_reject_get(self):
        for name in ("accounts:api_password_reset_verify", "accounts:api_password_reset"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 405)

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


class PasswordResetTests(TestCase):
    """메일을 못 쓰는 환경의 자기 확인 재설정 - 지식 기반이라 경계 조건을 촘촘히 본다."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="reset-me@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            first_name="홍길동",
            phone_number="010-1111-2222",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
        )
        self.verify_url = reverse("accounts:api_password_reset_verify")
        self.reset_url = reverse("accounts:api_password_reset")

    def _verify(self, email, phone_number, client=None):
        return (client or self.client).post(
            self.verify_url,
            data=json.dumps({"email": email, "phone_number": phone_number}),
            content_type="application/json",
        )

    def _reset(self, new_password, client=None):
        return (client or self.client).post(
            self.reset_url,
            data=json.dumps({"new_password": new_password}),
            content_type="application/json",
        )

    def test_reset_is_refused_without_passing_verification_first(self):
        """2단계 단독 호출로는 어떤 계정도 바꿀 수 없어야 한다."""
        response = self._reset(NEW_STRONG_PASSWORD)

        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG_PASSWORD))

    def test_reset_ignores_any_account_named_in_the_request_body(self):
        """대상 계정은 세션에서만 읽는다 - 본문에 남의 이메일을 넣어도 소용없어야 한다."""
        victim = User.objects.create_user(
            email="victim@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            phone_number="010-9999-8888",
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self._verify("reset-me@ax.com", "010-1111-2222")

        response = self.client.post(
            self.reset_url,
            data=json.dumps({"email": victim.email, "new_password": NEW_STRONG_PASSWORD}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        victim.refresh_from_db()
        self.user.refresh_from_db()
        self.assertTrue(victim.check_password(STRONG_PASSWORD))
        self.assertTrue(self.user.check_password(NEW_STRONG_PASSWORD))

    def test_wrong_phone_number_does_not_open_the_second_step(self):
        response = self._verify("reset-me@ax.com", "010-0000-0000")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._reset(NEW_STRONG_PASSWORD).status_code, 403)

    def test_unknown_email_and_missing_phone_look_the_same(self):
        no_phone = User.objects.create_user(
            email="no-phone@ax.com",
            password=STRONG_PASSWORD,
            _email_verified=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

        unknown = self._verify("nobody@ax.com", "010-1111-2222")
        missing = self._verify(no_phone.email, "010-1111-2222")

        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(unknown.json()["message"], missing.json()["message"])

    def test_successful_reset_changes_password_and_ends_other_sessions(self):
        signed_in = Client()
        signed_in.force_login(self.user)
        session_version = self.user.auth_session_version

        self.assertEqual(self._verify("Reset-Me@AX.com", "01011112222").status_code, 200)
        response = self._reset(NEW_STRONG_PASSWORD)

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_STRONG_PASSWORD))
        self.assertGreater(self.user.auth_session_version, session_version)
        # 재설정 전에 열려 있던 세션은 더 이상 대시보드를 열지 못한다.
        stale = signed_in.get(reverse("accounts:dashboard"))
        self.assertEqual(stale.status_code, 302)
        self.assertTrue(stale["Location"].startswith(reverse("accounts:login")))

    def test_grant_is_single_use(self):
        self._verify("reset-me@ax.com", "010-1111-2222")
        self._reset(NEW_STRONG_PASSWORD)

        response = self._reset(STRONG_PASSWORD)

        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_STRONG_PASSWORD))

    def test_weak_new_password_is_rejected(self):
        self._verify("reset-me@ax.com", "010-1111-2222")

        response = self._reset("1234")

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG_PASSWORD))

    def test_verification_attempts_are_rate_limited(self):
        for _ in range(5):
            self._verify("reset-me@ax.com", "010-0000-0000")

        response = self._verify("reset-me@ax.com", "010-0000-0000")

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
