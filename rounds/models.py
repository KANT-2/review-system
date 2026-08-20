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
    # 시작된 회차가 쓰고 있어 삭제할 수 없는(is_locked) 템플릿을 목록·새 회차 선택지에서
    # 치우는 용도 - 문항이 이미 제출된 평가 답변에 PROTECT로 물려 있어 실제 삭제는 못 하지만,
    # "안 쓸 템플릿"으로 표시는 해 둘 수 있어야 한다. archived_by는 기록용이라 계정이
    # 지워져도 보관 이력 자체는 남도록 SET_NULL로 둔다.
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archived_question_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "문항 템플릿"
        verbose_name_plural = "문항 템플릿 목록"
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

    def rounds_in_use(self):
        """이 템플릿을 쓰는 회차 제목 목록 - 보관 화면에서 왜 못 지우는지 보여줄 때 쓴다."""
        return list(
            EvaluationRound.objects.filter(Q(team_template=self) | Q(peer_template=self))
            .exclude(status=EvaluationRound.Status.DRAFT)
            .order_by("-completed_at", "-started_at")
            .values_list("title", flat=True)
        )


class TemplateQuestion(models.Model):
    class ResponseType(models.TextChoices):
        RATING_5 = "RATING_5", "1~5점"
        TEXT = "TEXT", "자유 서술"

    class Competency(models.TextChoices):
        TEAMWORK = "TEAMWORK", "팀워크"
        PROBLEM_SOLVING = "PROBLEM_SOLVING", "문제해결"
        DEV_UNDERSTANDING = "DEV_UNDERSTANDING", "개발이해도"
        RESPONSIBILITY = "RESPONSIBILITY", "책임감"
        COMMUNICATION = "COMMUNICATION", "커뮤니케이션"

    template = models.ForeignKey(
        QuestionTemplate, on_delete=models.PROTECT, related_name="questions"
    )
    response_type = models.CharField(max_length=12, choices=ResponseType.choices)
    prompt = models.CharField(max_length=500)
    is_required = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField()
    # 마이페이지 역량 분석(레이더차트)용 - 빈 값이면 그 문항은 역량 집계에서 빠진다.
    competency = models.CharField(max_length=20, choices=Competency.choices, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "문항"
        verbose_name_plural = "문항 목록"
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
    # 최종 점수 반영 비율(%) - 세 값의 합은 항상 100이어야 한다(clean()·DB 제약 둘 다 검증).
    # 기본값 40/60/0은 튜터 점수를 안 쓰는 기존 계산식(results.services 팀 40%+개인 60%)과
    # 같다 - tutor_score_weight가 0이면 채점 결과도 기존과 동일하다.
    team_score_weight = models.PositiveSmallIntegerField(default=40)
    personal_score_weight = models.PositiveSmallIntegerField(default=60)
    tutor_score_weight = models.PositiveSmallIntegerField(default=0)
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
        verbose_name = "평가 회차"
        verbose_name_plural = "평가 회차 목록"
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(evaluation_start_at__lt=models.F("evaluation_end_at")),
                name="rounds_evaluation_window_valid",
            ),
            models.CheckConstraint(
                condition=Q(target_team_count__gte=2), name="rounds_target_team_count_minimum"
            ),
            models.CheckConstraint(
                condition=Q(team_score_weight__gte=0, team_score_weight__lte=100)
                & Q(personal_score_weight__gte=0, personal_score_weight__lte=100)
                & Q(tutor_score_weight__gte=0, tutor_score_weight__lte=100),
                name="rounds_score_weight_range",
            ),
            models.CheckConstraint(
                condition=Q(
                    team_score_weight=100
                    - models.F("personal_score_weight")
                    - models.F("tutor_score_weight")
                ),
                name="rounds_score_weight_sums_to_100",
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
        weight_total = self.team_score_weight + self.personal_score_weight + self.tutor_score_weight
        if weight_total != 100:
            errors["team_score_weight"] = (
                f"팀·개인·튜터 점수 비율의 합은 100%여야 합니다 (현재 {weight_total}%)."
            )
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
        verbose_name = "회차 참가자"
        verbose_name_plural = "회차 참가자 목록"
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
