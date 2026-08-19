from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Category(models.TextChoices):
        NOTICE = "NOTICE", "공지"
        ROUND_CREATED = "ROUND_CREATED", "새 회차"
        TEAM_CREATED = "TEAM_CREATED", "새 팀"
        ROUND_COMPLETED = "ROUND_COMPLETED", "평가 종료"
        SUBMISSION_REMINDER = "SUBMISSION_REMINDER", "제출 안내"
        PARTICIPANT_COMPLETED = "PARTICIPANT_COMPLETED", "제출 완료"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="수신자",
    )
    category = models.CharField("종류", max_length=30, choices=Category.choices)
    title = models.CharField("제목", max_length=200)
    message = models.CharField("내용", max_length=300, blank=True)
    link = models.CharField("이동 경로", max_length=300, blank=True)
    created_at = models.DateTimeField("생성일", auto_now_add=True)
    read_at = models.DateTimeField("읽은 시각", null=True, blank=True)

    class Meta:
        verbose_name = "알림"
        verbose_name_plural = "알림 목록"
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("recipient", "read_at"))]

    def __str__(self):
        return f"{self.recipient_id}:{self.category}:{self.title}"
