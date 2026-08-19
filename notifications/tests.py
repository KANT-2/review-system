from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from notifications.models import Notification
from notifications.services import mark_all_read, mark_read, notify_users, unread_count


class NotifyUsersTests(TestCase):
    def setUp(self):
        self.students = [
            User.objects.create_user(
                email=f"notify-student-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
            )
            for index in range(1, 3)
        ]

    def test_notify_users_creates_one_row_per_recipient(self):
        notify_users(
            self.students,
            category=Notification.Category.NOTICE,
            title="새 공지가 등록되었습니다",
            message="점검 안내",
        )

        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(unread_count(self.students[0]), 1)

    def test_mark_read_only_affects_that_users_notification(self):
        notify_users(self.students, category=Notification.Category.NOTICE, title="공지")
        target = Notification.objects.get(recipient=self.students[0])

        mark_read(user=self.students[0], notification_id=target.pk)

        self.assertEqual(unread_count(self.students[0]), 0)
        self.assertEqual(unread_count(self.students[1]), 1)

    def test_mark_all_read_clears_every_unread_notification(self):
        notify_users(self.students, category=Notification.Category.NOTICE, title="공지")
        notify_users(self.students, category=Notification.Category.NOTICE, title="공지2")

        mark_all_read(self.students[0])

        self.assertEqual(unread_count(self.students[0]), 0)


class NotificationApiTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="notify-api-student@example.com",
            password="strong-test-password",
            first_name="학생",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_summary_lists_newest_first_with_unread_count(self):
        notify_users([self.student], category=Notification.Category.NOTICE, title="첫 번째")
        notify_users([self.student], category=Notification.Category.NOTICE, title="두 번째")
        self.client.force_login(self.student)

        response = self.client.get(reverse("notifications:summary"))

        data = response.json()
        self.assertEqual(data["unread_count"], 2)
        self.assertEqual(data["items"][0]["title"], "두 번째")
        self.assertEqual(data["items"][1]["title"], "첫 번째")

    def test_mark_read_endpoint_requires_post(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("notifications:summary"))

        self.assertEqual(response.status_code, 200)

    def test_mark_read_endpoint_updates_unread_count(self):
        notify_users([self.student], category=Notification.Category.NOTICE, title="공지")
        notification = Notification.objects.get(recipient=self.student)
        self.client.force_login(self.student)

        response = self.client.post(
            reverse("notifications:mark-read", kwargs={"notification_id": notification.pk})
        )

        self.assertEqual(response.json()["unread_count"], 0)

    def test_a_student_cannot_mark_another_students_notification_read(self):
        other = User.objects.create_user(
            email="notify-other-student@example.com",
            password="strong-test-password",
            first_name="다른학생",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        notify_users([other], category=Notification.Category.NOTICE, title="공지")
        notification = Notification.objects.get(recipient=other)
        self.client.force_login(self.student)

        self.client.post(
            reverse("notifications:mark-read", kwargs={"notification_id": notification.pk})
        )

        self.assertEqual(unread_count(other), 1)

    def test_anonymous_user_cannot_read_summary(self):
        response = self.client.get(reverse("notifications:summary"))

        self.assertNotEqual(response.status_code, 200)
