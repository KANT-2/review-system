from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    class Result(models.TextChoices):
        SUCCEEDED = "SUCCEEDED", "성공"
        FAILED = "FAILED", "실패"

    round = models.ForeignKey(
        "rounds.EvaluationRound",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64)
    result = models.CharField(max_length=12, choices=Result.choices)
    summary = models.JSONField(default=dict)
    request_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "감사 기록"
        verbose_name_plural = "감사 기록 목록"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("round", "created_at")),
            models.Index(fields=("actor", "created_at")),
        ]

    def __str__(self):
        return f"{self.action}:{self.target_type}:{self.target_id}"
