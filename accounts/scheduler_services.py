import json
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.email_services import (
    send_submission_reminder_email,
    send_tutor_announcement_email,
)
from accounts.models import ScheduledEmail, User
from notifications.models import Notification
from notifications.services import announce
from rounds.models import EvaluationRound
from rounds.services import pending_participant_rows


def process_scheduled_emails():
    """
    예약 발송 대기 중(PENDING)이며 예약 시각(scheduled_at)이 도래한 이메일 공지를 처리합니다.
    """
    now = timezone.now()
    pending_emails = ScheduledEmail.objects.filter(
        status=ScheduledEmail.Status.PENDING,
        scheduled_at__lte=now,
    )

    processed_count = 0
    for scheduled_item in pending_emails:
        try:
            recipients = []
            if scheduled_item.target_type == ScheduledEmail.TargetType.TEAM:
                if scheduled_item.target_team:
                    recipients = list(
                        User.objects.filter(
                            round_participations__team_membership__team=scheduled_item.target_team,
                            is_active=True,
                        )
                        .exclude(email="")
                        .distinct()
                    )
            elif scheduled_item.target_type in {
                ScheduledEmail.TargetType.SELECT,
                ScheduledEmail.TargetType.SINGLE,
            }:
                try:
                    user_ids = json.loads(scheduled_item.selected_user_ids_json or "[]")
                except Exception:
                    user_ids = []
                recipients = list(
                    User.objects.filter(
                        id__in=user_ids,
                        role=User.Role.STUDENT,
                        is_active=True,
                    ).exclude(email="")
                )
            else:
                # ALL 또는 default
                recipients = list(
                    User.objects.filter(role=User.Role.STUDENT, is_active=True).exclude(email="")
                )

            if recipients:
                # 즉시 발송과 같은 경로다 - 종 알림은 전원에게, 메일은 꺼두지 않은 사람에게만.
                mailed = announce(
                    recipients,
                    category=Notification.Category.NOTICE,
                    title=scheduled_item.subject,
                    message=scheduled_item.message,
                    email_sender=lambda users, item=scheduled_item: send_tutor_announcement_email(
                        subject=item.subject,
                        message=item.message,
                        recipient_emails=[user.email for user in users],
                    ),
                )
                scheduled_item.sent_count = len(mailed)
            else:
                scheduled_item.sent_count = 0

            scheduled_item.status = ScheduledEmail.Status.SENT
            scheduled_item.sent_at = timezone.now()
            scheduled_item.save(update_fields=["status", "sent_at", "sent_count"])
            processed_count += 1
        except Exception:
            scheduled_item.status = ScheduledEmail.Status.FAILED
            scheduled_item.save(update_fields=["status"])

    return processed_count


def process_auto_submission_reminders():
    """
    평가 회차가 진행 중(IN_PROGRESS)이며 종료 시각(evaluation_end_at)이 10분 이내로 다가온 경우,
    미제출 수강생들에게 제출 안내 이메일을 1회 자동 발송합니다.
    """
    now = timezone.now()
    threshold_time = now + timedelta(minutes=10)

    # 10분 이내 마감 예정이거나 이미 마감 시각이 다가왔으나 안내 메일이 발송되지 않은 회차
    rounds_to_remind = EvaluationRound.objects.filter(
        status=EvaluationRound.Status.IN_PROGRESS,
        auto_reminder_sent_at__isnull=True,
        evaluation_end_at__lte=threshold_time,
    )

    auto_reminded_rounds = 0
    for round_obj in rounds_to_remind:
        pending_students = []
        for row in pending_participant_rows(round_obj):
            student = row["participant"].user
            if not student.is_active:
                continue
            pending_students.append(student)

        def _send(users, round_obj=round_obj):
            for student in users:
                if not student.email:
                    continue
                name = student.first_name if student.first_name else student.email
                send_submission_reminder_email(round_obj, name, student.email)

        announce(
            pending_students,
            category=Notification.Category.SUBMISSION_REMINDER,
            title="마감이 얼마 남지 않았습니다",
            message=f"'{round_obj.title}' 회차의 팀·개인 평가를 아직 제출하지 않았습니다.",
            link=reverse("reviews:home"),
            email_sender=_send,
        )

        round_obj.auto_reminder_sent_at = now
        round_obj.save(update_fields=["auto_reminder_sent_at"])
        auto_reminded_rounds += 1

    return auto_reminded_rounds
