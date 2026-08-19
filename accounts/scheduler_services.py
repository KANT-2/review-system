import json
from datetime import timedelta

from django.utils import timezone

from accounts.email_services import (
    send_submission_reminder_email,
    send_tutor_announcement_email,
)
from accounts.models import ScheduledEmail, User
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
            recipient_emails = []
            if scheduled_item.target_type == ScheduledEmail.TargetType.TEAM:
                if scheduled_item.target_team:
                    recipient_emails = list(
                        scheduled_item.target_team.memberships.values_list(
                            "participant__user__email", flat=True
                        )
                    )
            elif scheduled_item.target_type in {
                ScheduledEmail.TargetType.SELECT,
                ScheduledEmail.TargetType.SINGLE,
            }:
                try:
                    user_ids = json.loads(scheduled_item.selected_user_ids_json or "[]")
                except Exception:
                    user_ids = []
                recipient_emails = list(
                    User.objects.filter(
                        id__in=user_ids,
                        role=User.Role.STUDENT,
                        is_active=True,
                    ).values_list("email", flat=True)
                )
            else:
                # ALL 또는 default
                recipient_emails = list(
                    User.objects.filter(role=User.Role.STUDENT, is_active=True).values_list(
                        "email", flat=True
                    )
                )

            if recipient_emails:
                sent_count = send_tutor_announcement_email(
                    subject=scheduled_item.subject,
                    message=scheduled_item.message,
                    recipient_emails=recipient_emails,
                )
                scheduled_item.sent_count = len(recipient_emails) if sent_count > 0 else 0
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
    미제출 수강생들에게 독촉 이메일을 1회 자동 발송합니다.
    """
    now = timezone.now()
    threshold_time = now + timedelta(minutes=10)

    # 10분 이내 마감 예정이거나 이미 마감 시각이 다가왔으나 독촉 메일이 발송되지 않은 회차
    rounds_to_remind = EvaluationRound.objects.filter(
        status=EvaluationRound.Status.IN_PROGRESS,
        auto_reminder_sent_at__isnull=True,
        evaluation_end_at__lte=threshold_time,
    )

    auto_reminded_rounds = 0
    for round_obj in rounds_to_remind:
        for row in pending_participant_rows(round_obj):
            student = row["participant"].user
            if not student.is_active or not student.email:
                continue
            name = student.first_name if student.first_name else student.email
            send_submission_reminder_email(round_obj, name, student.email)

        round_obj.auto_reminder_sent_at = now
        round_obj.save(update_fields=["auto_reminder_sent_at"])
        auto_reminded_rounds += 1

    return auto_reminded_rounds
