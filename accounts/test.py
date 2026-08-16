import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import User, WhitelistEmail


class AccountsTests(TestCase):
    def setUp(self):
        """테스트 기초 데이터 세팅"""
        self.approved_student = User.objects.create_user(
            email="student@ax.com",
            password="password123!",
            first_name="홍길동",
            phone_number="010-1234-5678",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
        )
        self.tutor_user = User.objects.create_user(
            email="tutor@ax.com",
            password="password123!",
            first_name="김튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
        )
        self.whitelist_entry = WhitelistEmail.objects.create(
            email="whitelist@ax.com",
            role=User.Role.STUDENT,
            session_info="2기",
        )

    def test_whitelist_user_auto_approved_on_signup(self):
        """화이트리스트 등록 유저의 가입 시 즉시 APPROVED 승인 검증"""
        response = self.client.post(
            reverse("accounts:api_signup"),
            data=json.dumps(
                {
                    "email": "whitelist@ax.com",
                    "password": "password123!",
                    "first_name": "화이트",
                    "phone_number": "010-1111-2222",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="whitelist@ax.com")
        self.assertEqual(user.approval_status, User.ApprovalStatus.APPROVED)

    def test_non_whitelist_user_pending_on_signup(self):
        """화이트리스트 미등록 유저의 가입 시 PENDING 승인 대기 검증"""
        response = self.client.post(
            reverse("accounts:api_signup"),
            data=json.dumps(
                {
                    "email": "newbie@ax.com",
                    "password": "password123!",
                    "first_name": "신규",
                    "phone_number": "010-3333-4444",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="newbie@ax.com")
        self.assertEqual(user.approval_status, User.ApprovalStatus.PENDING)

    def test_login_blocked_for_pending_user(self):
        """승인 대기(PENDING) 상태 유저의 로그인 시도 차단 검증"""
        User.objects.create_user(
            email="pending@ax.com",
            password="password123!",
            approval_status=User.ApprovalStatus.PENDING,
        )
        response = self.client.post(
            reverse("accounts:login"),
            data={
                "email": "pending@ax.com",
                "password": "password123!",
            },
        )
        self.assertRedirects(response, reverse("accounts:login"))

    def test_tutor_api_permission_denied_for_students(self):
        """일반 학생 계정이 튜터 승인 API 호출 시 403 Forbidden 차단 검증"""
        target_user = User.objects.create_user(
            email="target@ax.com",
            password="password123!",
            approval_status=User.ApprovalStatus.PENDING,
        )
        self.client.force_login(self.approved_student)
        response = self.client.post(
            reverse("accounts:api_approve_user", kwargs={"user_id": target_user.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_tutor_api_success_for_tutor(self):
        """튜터 계정의 학생 가입 승인 API 호출 성공 및 상태 변경 검증"""
        target_user = User.objects.create_user(
            email="target2@ax.com",
            password="password123!",
            approval_status=User.ApprovalStatus.PENDING,
        )
        self.client.force_login(self.tutor_user)
        response = self.client.post(
            reverse("accounts:api_approve_user", kwargs={"user_id": target_user.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        target_user.refresh_from_db()
        self.assertEqual(target_user.approval_status, User.ApprovalStatus.APPROVED)

    def test_profile_update_api(self):
        """프로필 비동기 수정 API 호출 시 사용자 정보 변경 검증"""
        self.client.force_login(self.approved_student)
        response = self.client.post(
            reverse("accounts:api_update_profile"),
            data=json.dumps(
                {
                    "first_name": "김수정",
                    "session_info": "3기 종합반",
                    "phone_number": "010-8888-7777",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.approved_student.refresh_from_db()
        self.assertEqual(self.approved_student.first_name, "김수정")
        self.assertEqual(self.approved_student.session_info, "3기 종합반")
        self.assertEqual(self.approved_student.phone_number, "010-8888-7777")
