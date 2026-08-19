from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.email_services import (
    send_results_released_email,
    send_round_started_email,
    send_submission_reminder_email,
    send_tutor_announcement_email,
)
from accounts.models import User
from rounds.models import EvaluationRound


class EmailNotificationServicesTestCase(TestCase):
    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from accounts.models import User

        self.user = User.objects.create_user(email="creator@example.com", password="password")
        self.round_obj = EvaluationRound.objects.create(
            title="1차 미니프로젝트 발표회",
            status=EvaluationRound.Status.DRAFT,
            evaluation_start_at=timezone.now(),
            evaluation_end_at=timezone.now() + timedelta(days=7),
            created_by=self.user,
        )

    def test_send_tutor_announcement_email(self):
        recipients = ["studentA@example.com", "studentB@example.com"]
        sent_count = send_tutor_announcement_email(
            "팀 긴급 공지", "1조 발표 일정 변경 안내", recipients
        )

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("[AX 평가 공지]", mail.outbox[0].subject)

    def test_send_round_started_email(self):
        recipients = ["student1@example.com"]
        sent_count = send_round_started_email(self.round_obj, recipients)

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("1차 미니프로젝트 발표회", mail.outbox[0].subject)
        self.assertIn("평가가 개시되었습니다", mail.outbox[0].subject)

    def test_send_results_released_email(self):
        recipients = ["student1@example.com"]
        sent_count = send_results_released_email(self.round_obj, recipients)

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("최종 성적 및 피드백이 공개되었습니다", mail.outbox[0].subject)

    def test_send_submission_reminder_email(self):
        sent_count = send_submission_reminder_email(self.round_obj, "홍길동", "hong@example.com")

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("평가 제출 안내", mail.outbox[0].subject)


@override_settings(SITE_URL="https://oaknamu.com")
class EmailLinkTestCase(TestCase):
    """메일 본문 링크가 배포 주소로 나가는지 확인한다.

    링크 주소가 함수 기본 인자에 박혀 있었고 호출부는 아무도 값을 넘기지 않아서,
    운영에서 나간 메일의 버튼이 전부 http://127.0.0.1:8000/ 을 가리켰다.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="creator2@example.com", password="password")
        self.round_obj = EvaluationRound.objects.create(
            title="2차 미니프로젝트 발표회",
            status=EvaluationRound.Status.DRAFT,
            evaluation_start_at=timezone.now(),
            evaluation_end_at=timezone.now() + timedelta(days=7),
            created_by=self.user,
        )

    def body(self):
        return mail.outbox[0].alternatives[0][0]

    def assert_points_at_site(self, url):
        body = self.body()
        self.assertIn(url, body)
        self.assertNotIn("127.0.0.1", body)
        self.assertNotIn("localhost", body)

    def test_announcement_link_uses_the_deployed_dashboard(self):
        send_tutor_announcement_email("공지", "본문", ["studentA@example.com"])

        self.assert_points_at_site(f"https://oaknamu.com{reverse('accounts:dashboard')}")

    def test_round_started_link_uses_the_deployed_review_page(self):
        send_round_started_email(self.round_obj, ["student1@example.com"])

        self.assert_points_at_site(f"https://oaknamu.com{reverse('reviews:status')}")

    def test_results_released_link_uses_the_deployed_result_page(self):
        send_results_released_email(self.round_obj, ["student1@example.com"])

        self.assert_points_at_site(f"https://oaknamu.com{reverse('results:me')}")

    def test_submission_reminder_link_uses_the_deployed_review_page(self):
        send_submission_reminder_email(self.round_obj, "홍길동", "hong@example.com")

        self.assert_points_at_site(f"https://oaknamu.com{reverse('reviews:status')}")

    def test_caller_supplied_url_still_wins(self):
        send_tutor_announcement_email(
            "공지", "본문", ["studentA@example.com"], dashboard_url="https://example.org/custom/"
        )

        self.assertIn("https://example.org/custom/", self.body())

    @override_settings(SITE_URL="http://127.0.0.1:8000")
    def test_falls_back_to_the_local_address_when_site_url_is_local(self):
        """로컬 개발에서는 그대로 로컬 주소가 나와야 한다."""
        send_tutor_announcement_email("공지", "본문", ["studentA@example.com"])

        self.assertIn(f"http://127.0.0.1:8000{reverse('accounts:dashboard')}", self.body())
