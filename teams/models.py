from django.db import models
from django.db.models import Q


class Team(models.Model):
    round = models.ForeignKey(
        "rounds.EvaluationRound", on_delete=models.PROTECT, related_name="teams"
    )
    team_number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("team_number",)
        constraints = [
            models.UniqueConstraint(fields=("round", "team_number"), name="teams_number_unique"),
            models.CheckConstraint(condition=Q(team_number__gte=1), name="teams_number_positive"),
        ]

    def __str__(self):
        return f"{self.round} / {self.name}"


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="memberships")
    participant = models.OneToOneField(
        "rounds.RoundParticipant", on_delete=models.PROTECT, related_name="team_membership"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("team__team_number", "participant__student_number_snapshot")

    def __str__(self):
        return f"{self.team} / {self.participant.display_name_snapshot}"
