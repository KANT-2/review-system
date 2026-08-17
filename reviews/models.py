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
