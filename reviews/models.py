from django.conf import settings
from django.db import models
from django.db.models import Q


class ReviewSubmission(models.Model):
    class ReviewType(models.TextChoices):
        TEAM = "TEAM", "팀 평가"
        PEER = "PEER", "개인 평가"

    round = models.ForeignKey(
        "rounds.EvaluationRound", on_delete=models.PROTECT, related_name="review_submissions"
    )
    review_type = models.CharField(max_length=8, choices=ReviewType.choices)
    evaluator = models.ForeignKey(
        "rounds.RoundParticipant",
        on_delete=models.PROTECT,
        related_name="written_reviews",
    )
    target_team = models.ForeignKey(
        "teams.Team",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_reviews",
    )
    target_participant = models.ForeignKey(
        "rounds.RoundParticipant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_peer_reviews",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("submitted_at",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        review_type="TEAM",
                        target_team__isnull=False,
                        target_participant__isnull=True,
                    )
                    | Q(
                        review_type="PEER",
                        target_team__isnull=True,
                        target_participant__isnull=False,
                    )
                ),
                name="reviews_submission_target_matches_type",
            ),
            models.CheckConstraint(
                condition=Q(target_participant__isnull=True)
                | ~Q(evaluator=models.F("target_participant")),
                name="reviews_no_self_peer_review",
            ),
            models.UniqueConstraint(
                fields=("round", "evaluator", "target_team"),
                condition=Q(review_type="TEAM"),
                name="reviews_team_target_unique",
            ),
            models.UniqueConstraint(
                fields=("round", "evaluator", "target_participant"),
                condition=Q(review_type="PEER"),
                name="reviews_peer_target_unique",
            ),
        ]

    def __str__(self):
        target = self.target_team or self.target_participant
        return f"{self.evaluator} → {target}"


class ReviewAnswer(models.Model):
    submission = models.ForeignKey(
        ReviewSubmission, on_delete=models.CASCADE, related_name="answers"
    )
    question = models.ForeignKey(
        "rounds.TemplateQuestion", on_delete=models.PROTECT, related_name="answers"
    )
    rating_value = models.PositiveSmallIntegerField(null=True, blank=True)
    text_value = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("question__display_order",)
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "question"), name="reviews_answer_question_unique"
            ),
            models.CheckConstraint(
                condition=(
                    Q(rating_value__isnull=False, text_value="")
                    | (Q(rating_value__isnull=True) & ~Q(text_value=""))
                ),
                name="reviews_answer_exactly_one_value",
            ),
            models.CheckConstraint(
                condition=Q(rating_value__isnull=True)
                | Q(rating_value__gte=1, rating_value__lte=5),
                name="reviews_answer_rating_range",
            ),
        ]

    def __str__(self):
        return f"{self.submission_id}:{self.question_id}"


class ReviewFinalSubmission(models.Model):
    """평가 유형별 최종 제출 기록.

    개별 제출은 최종 제출 전까지 다시 저장할 수 있고, 이 기록이 생기면 해당 유형의
    평가가 잠긴다. 유형별로 한 번만 남는다.
    """

    round = models.ForeignKey(
        "rounds.EvaluationRound",
        on_delete=models.PROTECT,
        related_name="review_final_submissions",
    )
    evaluator = models.ForeignKey(
        "rounds.RoundParticipant",
        on_delete=models.PROTECT,
        related_name="review_final_submissions",
    )
    review_type = models.CharField(max_length=8, choices=ReviewSubmission.ReviewType.choices)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("round", "evaluator", "review_type"),
                name="reviews_final_submission_unique",
            ),
        ]

    def __str__(self):
        return f"{self.evaluator_id}:{self.review_type}:final"


class TutorReview(models.Model):
    """튜터가 수강생 한 명에게 남기는 개인 평가.

    학생끼리 하는 개인 평가(ReviewSubmission)와 저장을 분리한다 - 평가자가 회차 참가자가
    아니라 튜터 계정이고, 최종점수 계산에는 아직 반영하지 않기 때문이다(results.services의
    TUTOR_WEIGHT 참고 - 비율이 팀 협의로 확정되면 그때 계산에 연결한다).

    같은 튜터가 같은 학생을 두 번 만들지 않도록 회차·튜터·대상 조합을 유니크로 묶는다.
    """

    round = models.ForeignKey(
        "rounds.EvaluationRound", on_delete=models.PROTECT, related_name="tutor_reviews"
    )
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tutor_reviews"
    )
    target_participant = models.ForeignKey(
        "rounds.RoundParticipant",
        on_delete=models.PROTECT,
        related_name="received_tutor_reviews",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("target_participant__student_number_snapshot", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("round", "evaluator", "target_participant"),
                name="reviews_tutor_review_target_unique",
            ),
        ]

    def __str__(self):
        return f"{self.evaluator} → {self.target_participant} (튜터)"


class TutorReviewAnswer(models.Model):
    review = models.ForeignKey(TutorReview, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(
        "rounds.TemplateQuestion", on_delete=models.PROTECT, related_name="tutor_answers"
    )
    rating_value = models.PositiveSmallIntegerField(null=True, blank=True)
    text_value = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("question__display_order",)
        constraints = [
            models.UniqueConstraint(
                fields=("review", "question"), name="reviews_tutor_answer_question_unique"
            ),
            models.CheckConstraint(
                condition=(
                    Q(rating_value__isnull=False, text_value="")
                    | (Q(rating_value__isnull=True) & ~Q(text_value=""))
                ),
                name="reviews_tutor_answer_exactly_one_value",
            ),
            models.CheckConstraint(
                condition=Q(rating_value__isnull=True)
                | Q(rating_value__gte=1, rating_value__lte=5),
                name="reviews_tutor_answer_rating_range",
            ),
        ]

    def __str__(self):
        return f"{self.review_id}:{self.question_id}"
