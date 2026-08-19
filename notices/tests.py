from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from notices.models import Notice
from notices.services import delete_notice, toggle_notice_publish


class NoticeModelTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="notice-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_blank_title_is_rejected(self):
        notice = Notice(title="   ", content="내용", created_by=self.tutor)
        with self.assertRaises(ValidationError):
            notice.save()

    def test_blank_content_is_rejected(self):
        notice = Notice(title="제목", content="   ", created_by=self.tutor)
        with self.assertRaises(ValidationError):
            notice.save()

    def test_new_notice_defaults_to_unpublished(self):
        notice = Notice.objects.create(title="제목", content="내용", created_by=self.tutor)
        self.assertFalse(notice.is_published)


class NoticeServiceTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="notice-service-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.notice = Notice.objects.create(
            title="원본 제목", content="원본 내용", created_by=self.tutor, is_published=False
        )

    def test_toggle_notice_publish_flips_state_and_records_audit_event(self):
        toggle_notice_publish(notice_id=self.notice.pk, actor=self.tutor)
        self.notice.refresh_from_db()
        self.assertTrue(self.notice.is_published)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="NOTICE_PUBLISHED", target_id=str(self.notice.pk)
            ).exists()
        )

        toggle_notice_publish(notice_id=self.notice.pk, actor=self.tutor)
        self.notice.refresh_from_db()
        self.assertFalse(self.notice.is_published)

    def test_delete_notice_removes_row(self):
        delete_notice(notice_id=self.notice.pk, actor=self.tutor)
        self.assertFalse(Notice.objects.filter(pk=self.notice.pk).exists())

    def test_delete_missing_notice_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            delete_notice(notice_id=999999, actor=self.tutor)


class NoticePortalAccessTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="notice-portal-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student = User.objects.create_user(
            email="notice-portal-student@example.com",
            password="strong-test-password",
            first_name="학생",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_student_cannot_access_notice_portal(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("notices:portal"))
        self.assertEqual(response.status_code, 403)

    def test_tutor_can_access_notice_portal(self):
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("notices:portal"))
        self.assertEqual(response.status_code, 200)

    def test_tutor_can_create_published_notice(self):
        self.client.force_login(self.tutor)
        self.client.post(
            reverse("notices:notice-create"),
            {"title": "새 공지", "content": "내용", "is_published": "on"},
        )
        notice = Notice.objects.get(title="새 공지")
        self.assertTrue(notice.is_published)
        self.assertEqual(notice.created_by, self.tutor)

    def test_student_cannot_create_notice(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("notices:notice-create"), {"title": "새 공지", "content": "내용"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Notice.objects.filter(title="새 공지").exists())
