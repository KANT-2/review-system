from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import ScheduledEmail, User


class TutorAnnouncementViewTestCase(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="tutor@example.com",
            password="password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student_a = User.objects.create_user(
            email="student-a@example.com",
            password="password",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student_b = User.objects.create_user(
            email="student-b@example.com",
            password="password",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.tutor)

    def test_account_admin_uses_existing_form_style_without_emoji(self):
        response = self.client.get(reverse("accounts:account_admin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="send_target_type"')
        self.assertContains(response, '<textarea id="email_message"', html=False)
        self.assertNotContains(response, "📢")
        self.assertNotContains(response, "📅")
        self.assertNotContains(response, "✉️")

    def test_all_target_ignores_stale_selected_user_ids(self):
        response = self.client.post(
            reverse("accounts:send_announcement"),
            {
                "subject": "전체 공지",
                "message": "전체 수강생 대상 공지입니다.",
                "send_target_type": "all",
                "send_type": "now",
                "selected_user_ids": [str(self.student_a.pk)],
            },
        )

        self.assertRedirects(response, reverse("accounts:account_admin"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(
            mail.outbox[0].bcc,
            [self.student_a.email, self.student_b.email],
        )

    def test_selected_target_requires_at_least_one_active_student(self):
        response = self.client.post(
            reverse("accounts:send_announcement"),
            {
                "subject": "개별 공지",
                "message": "선택 대상 공지입니다.",
                "send_target_type": "select",
                "send_type": "now",
            },
        )

        self.assertRedirects(response, reverse("accounts:account_admin"))
        self.assertEqual(len(mail.outbox), 0)

    def test_scheduled_send_requires_datetime(self):
        response = self.client.post(
            reverse("accounts:send_announcement"),
            {
                "subject": "예약 공지",
                "message": "예약 발송할 공지입니다.",
                "send_target_type": "all",
                "send_type": "scheduled",
                "scheduled_at": "",
            },
        )

        self.assertRedirects(response, reverse("accounts:account_admin"))
        self.assertFalse(ScheduledEmail.objects.exists())
        self.assertEqual(len(mail.outbox), 0)
