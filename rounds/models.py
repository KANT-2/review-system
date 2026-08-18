from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class QuestionTemplate(models.Model):
    class Category(models.TextChoices):
        TEAM = "TEAM", "팀 평가"
        PEER = "PEER", "개인 평가"

    name = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True, default="")
    category = models.CharField(max_length=8, choices=Category.choices)
    copied_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="copies"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="question_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category", "name")
        indexes = [models.Index(fields=("category", "name"))]
        constraints = [
            models.CheckConstraint(condition=~Q(name=""), name="rounds_template_name_not_blank"),
            models.CheckConstraint(
                condition=Q(copied_from__isnull=True) | ~Q(copied_from=models.F("id")),
                name="rounds_template_not_self_copy",
            ),
        ]

    def __str__(self):
        return f"[{self.get_category_display()}] {self.name}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.get(pk=self.pk).is_locked:
            raise ValidationError("시작된 회차가 사용하는 템플릿은 변경할 수 없습니다.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_locked:
            raise ValidationError("시작된 회차가 사용하는 템플릿은 삭제할 수 없습니다.")
        return super().delete(*args, **kwargs)

    def clean(self):
        if not self.name.strip():
            raise ValidationError({"name": "템플릿 이름을 입력해 주세요."})
        if self.copied_from_id and self.copied_from.category != self.category:
            raise ValidationError({"copied_from": "같은 유형의 템플릿만 복제할 수 있습니다."})

    @property
    def is_locked(self):
        return (
            self.team_rounds.exclude(status=EvaluationRound.Status.DRAFT).exists()
            or self.peer_rounds.exclude(status=EvaluationRound.Status.DRAFT).exists()
        )


class TemplateQuestion(models.Model):
    class ResponseType(models.TextChoices):
        RATING_5 = "RATING_5", "1~5점"
        TEXT = "TEXT", "자유 서술"

    template = models.ForeignKey(
        QuestionTemplate, on_delete=models.PROTECT, related_name="questions"
    )
    response_type = models.CharField(max_length=12, choices=ResponseType.choices)
    prompt = models.CharField(max_length=500)
    is_required = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("template", "display_order"), name="rounds_question_order_unique"
            ),
            models.CheckConstraint(
                condition=Q(display_order__gte=1), name="rounds_question_order_positive"
            ),
            models.CheckConstraint(
                condition=~Q(prompt=""), name="rounds_question_prompt_not_blank"
            ),
        ]

    def __str__(self):
        return f"{self.display_order}. {self.prompt}"

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.template.is_locked:
            raise ValidationError("시작된 회차가 사용하는 문항은 삭제할 수 없습니다.")
        return super().delete(*args, **kwargs)

    def clean(self):
        if not self.prompt.strip():
            raise ValidationError({"prompt": "문항 내용을 입력해 주세요."})
        if self.template_id and self.template.is_locked:
            raise ValidationError("시작된 회차가 사용하는 문항은 변경할 수 없습니다.")


class EvaluationRound(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "준비 중"
        IN_PROGRESS = "IN_PROGRESS", "평가 진행 중"
        COMPLETED = "COMPLETED", "완료"

    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    evaluation_start_at = models.DateTimeField()
    evaluation_end_at = models.DateTimeField()
    target_team_count = models.PositiveSmallIntegerField(default=2)
    team_template = models.ForeignKey(
        QuestionTemplate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="team_rounds",
    )
    peer_template = models.ForeignKey(
        QuestionTemplate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="peer_rounds",
    )
    lock_version = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_rounds"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    auto_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(evaluation_start_at__lt=models.F("evaluation_end_at")),
                name="rounds_evaluation_window_valid",
            ),
            models.CheckConstraint(
                condition=Q(target_team_count__gte=2), name="rounds_target_team_count_minimum"
            ),
            models.UniqueConstraint(
                fields=("status",),
                condition=Q(status="IN_PROGRESS"),
                name="rounds_single_in_progress",
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        errors = {}
        if self.evaluation_start_at and self.evaluation_end_at:
            if self.evaluation_start_at >= self.evaluation_end_at:
                errors["evaluation_end_at"] = "종료 시각은 시작 시각보다 늦어야 합니다."
        if self.target_team_count < 2:
            errors["target_team_count"] = "팀 수는 2개 이상이어야 합니다."
        if self.team_template_id and self.team_template.category != QuestionTemplate.Category.TEAM:
            errors["team_template"] = "팀 평가 템플릿을 선택해 주세요."
        if self.peer_template_id and self.peer_template.category != QuestionTemplate.Category.PEER:
            errors["peer_template"] = "개인 평가 템플릿을 선택해 주세요."
        if errors:
            raise ValidationError(errors)


class RoundParticipant(models.Model):
    round = models.ForeignKey(
        EvaluationRound, on_delete=models.PROTECT, related_name="participants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="round_participations"
    )
    student_number_snapshot = models.CharField(max_length=32)
    display_name_snapshot = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("student_number_snapshot", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("round", "user"), name="rounds_participant_user_unique"
            ),
            models.UniqueConstraint(
                fields=("round", "student_number_snapshot"),
                name="rounds_participant_number_unique",
            ),
        ]

    def __str__(self):
        return f"{self.round} / {self.display_name_snapshot}"
