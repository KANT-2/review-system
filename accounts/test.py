from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, WhitelistEmail


class AccountsAuthTests(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. 화이트리스트 사전 등록 데이터
        WhitelistEmail.objects.create(
            email="whitelisted@ax.com",
            name="화이트학생",
            role=User.Role.STUDENT,
            session_info="4기 풀스택"
        )

        # 2. 튜터 계정
        self.tutor = User.objects.create_user(
            username="tutor@ax.com",
            email="tutor@ax.com",
            password="password123",
            first_name="박교수",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True,
            is_staff=True
        )

        # 3. 일반 승인 완료 학생 계정
        self.approved_student = User.objects.create_user(
            username="student@ax.com",
            email="student@ax.com",
            password="password123",
            first_name="김학생",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=True
        )

    def test_signup_whitelist_auto_approved(self):
        """화이트리스트에 등록된 이메일로 가입 시 즉시 APPROVED 승인 처리 검증"""
        response = self.client.post(reverse("accounts:signup"), {
            "name": "화이트학생",
            "email": "whitelisted@ax.com",
            "password": "SecurePassword123!"
        })
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(email="whitelisted@ax.com")
        self.assertEqual(user.approval_status, User.ApprovalStatus.APPROVED)
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertEqual(user.session_info, "4기 풀스택")

    def test_signup_non_whitelist_pending(self):
        """화이트리스트 미등록 이메일로 가입 시 PENDING 대기 상태 처리 검증"""
        response = self.client.post(reverse("accounts:signup"), {
            "name": "일반신청자",
            "email": "outsider@ax.com",
            "password": "SecurePassword123!"
        })
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(email="outsider@ax.com")
        self.assertEqual(user.approval_status, User.ApprovalStatus.PENDING)

    def test_login_blocked_for_pending_user(self):
        """승인 대기(PENDING) 상태 유저의 로그인 시도 차단 검증"""
        pending_user = User.objects.create_user(
            username="pending@ax.com",
            email="pending@ax.com",
            password="password123",
            approval_status=User.ApprovalStatus.PENDING
        )
        response = self.client.post(reverse("accounts:login"), {
            "email": "pending@ax.com",
            "password": "password123"
        })
        # 세션에 로그인되지 않고 로그인 페이지가 다시 렌더링되어야 함
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)

    def test_onboarding_guard_redirects_unonboarded_user(self):
        """온보딩 미완료 유저(is_onboarded=False) 대시보드 접근 시 온보딩 페이지로 강제 리다이렉트 검증"""
        unonboarded_user = User.objects.create_user(
            username="newbie@ax.com",
            email="newbie@ax.com",
            password="password123",
            approval_status=User.ApprovalStatus.APPROVED,
            is_onboarded=False
        )
        self.client.force_login(unonboarded_user)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertRedirects(response, reverse("accounts:onboarding"))

    def test_tutor_api_permission_denied_for_students(self):
        """일반 학생 계정이 튜터 승인 API 호출 시 403 Forbidden 차단 검증"""
        target_user = User.objects.create_user(
            username="target@ax.com",
            email="target@ax.com",
            password="password123",
            approval_status=User.ApprovalStatus.PENDING
        )
        self.client.force_login(self.approved_student)
        response = self.client.post(reverse("accounts:api_approve_user", kwargs={"user_id": target_user.id}))
        self.assertEqual(response.status_code, 403)

    def test_tutor_api_success_for_tutor(self):
        """튜터 계정의 학생 가입 승인 API 호출 성공 및 상태 변경 검증"""
        target_user = User.objects.create_user(
            username="target2@ax.com",
            email="target2@ax.com",
            password="password123",
            approval_status=User.ApprovalStatus.PENDING
        )
        self.client.force_login(self.tutor)
        response = self.client.post(reverse("accounts:api_approve_user", kwargs={"user_id": target_user.id}))
        self.assertEqual(response.status_code, 200)

        target_user.refresh_from_db()
        self.assertEqual(target_user.approval_status, User.ApprovalStatus.APPROVED)

    def test_profile_update_api(self):
        """프로필 비동기 수정 API 호출 시 사용자 정보 변경 검증"""
        self.client.force_login(self.approved_student)
        response = self.client.post(reverse("accounts:api_update_profile"), {
            "name": "김수정",
            "phone": "010-8888-7777"
        })
        self.assertEqual(response.status_code, 200)

        self.approved_student.refresh_from_db()
        self.assertEqual(self.approved_student.first_name, "김수정")
        self.assertEqual(self.approved_student.phone, "010-8888-7777")