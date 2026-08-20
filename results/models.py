from django.conf import settings
from django.db import models
from django.db.models import Q


class CalculationRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "RUNNING", "계산 중"
        SUCCEEDED = "SUCCEEDED", "성공"
        FAILED = "FAILED", "실패"

    round = models.ForeignKey(
        "rounds.EvaluationRound", on_delete=models.PROTECT, related_name="calculation_runs"
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    is_active = models.BooleanField(default=False)
    formula_version = models.CharField(max_length=32)
    input_digest = models.CharField(max_length=64, blank=True, default="")
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="calculation_runs"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(blank=True, default="")
    winner_published_at = models.DateTimeField(null=True, blank=True)
    team_ranking_published_at = models.DateTimeField(null=True, blank=True)
    my_score_published_at = models.DateTimeField(null=True, blank=True)
    peer_ranking_published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "채점"
        verbose_name_plural = "채점 목록"
        ordering = ("-version",)
        constraints = [
            models.UniqueConstraint(fields=("round", "version"), name="results_run_version_unique"),
            models.UniqueConstraint(
                fields=("round",),
                condition=Q(is_active=True),
                name="results_single_active_run",
            ),
            models.CheckConstraint(
                condition=Q(is_active=False) | Q(status="SUCCEEDED"),
                name="results_active_run_succeeded",
            ),
        ]

    def __str__(self):
        return f"{self.round} v{self.version}"


class TutorNote(models.Model):
    """수강생 한 명에 대한 튜터 전용 메모 기록.

    수강생 관리 화면(운영자 전용)에서만 읽고 쓴다 - 학생 화면과 학생용 조회 경로에서는
    절대 노출하지 않는다. 회차와 무관하게 학생당 여러 건이 쌓이는 이력이다 - 언제 무슨
    맥락으로 남겼는지가 중요해서 새로 쓴 메모가 이전 메모를 덮어쓰지 않는다.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes"
    )
    body = models.TextField(max_length=1000)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tutor_notes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "튜터 메모"
        verbose_name_plural = "튜터 메모 목록"
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(condition=~Q(body=""), name="results_tutor_note_not_blank"),
        ]

    def __str__(self):
        return f"{self.student} 메모 ({self.created_at:%Y-%m-%d})"


class EvaluationResult(models.Model):
    class ResultType(models.TextChoices):
        TEAM = "TEAM", "팀"
        INDIVIDUAL = "INDIVIDUAL", "개인"

    class DataStatus(models.TextChoices):
        NOT_APPLICABLE = "NOT_APPLICABLE", "대상 없음"
        COMPLETE = "COMPLETE", "완료"
        PARTIAL = "PARTIAL", "일부 제출"
        NO_DATA = "NO_DATA", "데이터 없음"

    calculation_run = models.ForeignKey(
        CalculationRun, on_delete=models.PROTECT, related_name="results"
    )
    result_type = models.CharField(max_length=12, choices=ResultType.choices)
    team = models.ForeignKey(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evaluation_results",
    )
    participant = models.ForeignKey(
        "rounds.RoundParticipant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evaluation_results",
    )
    team_score_raw = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    peer_score_raw = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    tutor_score_raw = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    final_score_raw = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    display_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    primary_rank = models.PositiveIntegerField(null=True, blank=True)
    peer_rank = models.PositiveIntegerField(null=True, blank=True)
    expected_count = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    coverage = models.DecimalField(max_digits=7, decimal_places=6, null=True, blank=True)
    data_status = models.CharField(max_length=16, choices=DataStatus.choices)

    class Meta:
        verbose_name = "채점 결과"
        verbose_name_plural = "채점 결과 목록"
        ordering = ("result_type", "primary_rank", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(result_type="TEAM", team__isnull=False, participant__isnull=True)
                    | Q(result_type="INDIVIDUAL", team__isnull=True, participant__isnull=False)
                ),
                name="results_target_matches_type",
            ),
            models.CheckConstraint(
                condition=Q(valid_count__lte=models.F("expected_count")),
                name="results_valid_not_above_expected",
            ),
            models.CheckConstraint(
                condition=Q(team_score_raw__isnull=True)
                | Q(team_score_raw__gte=1, team_score_raw__lte=5),
                name="results_team_score_five_point_range",
            ),
            models.CheckConstraint(
                condition=Q(peer_score_raw__isnull=True)
                | Q(peer_score_raw__gte=1, peer_score_raw__lte=5),
                name="results_peer_score_five_point_range",
            ),
            models.CheckConstraint(
                condition=Q(tutor_score_raw__isnull=True)
                | Q(tutor_score_raw__gte=1, tutor_score_raw__lte=5),
                name="results_tutor_score_five_point_range",
            ),
            models.CheckConstraint(
                condition=Q(final_score_raw__isnull=True)
                | Q(final_score_raw__gte=1, final_score_raw__lte=5),
                name="results_final_score_five_point_range",
            ),
            models.CheckConstraint(
                condition=Q(display_score__isnull=True)
                | Q(display_score__gte=1, display_score__lte=5),
                name="results_display_score_five_point_range",
            ),
            models.UniqueConstraint(
                fields=("calculation_run", "team"),
                condition=Q(result_type="TEAM"),
                name="results_team_target_unique",
            ),
            models.UniqueConstraint(
                fields=("calculation_run", "participant"),
                condition=Q(result_type="INDIVIDUAL"),
                name="results_individual_target_unique",
            ),
        ]

    def __str__(self):
        return f"{self.calculation_run} / {self.team or self.participant}"
