from dataclasses import dataclass
from math import ceil

from django.utils import timezone

from results.models import EvaluationResult
from reviews.services import current_participation, peer_targets, team_targets


@dataclass(frozen=True)
class EvaluationProgress:
    label: str
    completed: int
    expected: int

    @property
    def percent(self):
        return 100 if self.expected == 0 else round(self.completed / self.expected * 100)


def _published_result_rows(user):
    return list(
        EvaluationResult.objects.filter(
            result_type=EvaluationResult.ResultType.INDIVIDUAL,
            participant__user=user,
            calculation_run__is_active=True,
            calculation_run__my_score_published_at__isnull=False,
        )
        .select_related("calculation_run__round")
        .order_by("-calculation_run__round__completed_at")[:3]
    )


def _serialize_result(result):
    run = result.calculation_run
    return {
        "round_name": run.round.title,
        "team_score": result.team_score_raw,
        "peer_score": result.peer_score_raw,
        "final_score": result.final_score_raw,
        "primary_rank": result.primary_rank if run.peer_ranking_published_at else None,
        "expected_count": result.expected_count,
        "valid_count": result.valid_count,
        "coverage": result.coverage,
        "data_status": result.data_status,
    }


def _latest_result(user):
    rows = _published_result_rows(user)
    return _serialize_result(rows[0]) if rows else None


def build_student_result_portal(user):
    rows = _published_result_rows(user)
    if not rows:
        return None
    serialized = [_serialize_result(result) for result in rows]
    return {
        "latest_result": serialized[0],
        "score_history": serialized,
    }


def build_student_portal(user):
    participant = current_participation(user)
    if not participant:
        return None
    round_obj = participant.round
    team_rows = team_targets(participant)
    peer_rows = peer_targets(participant)
    team_progress = EvaluationProgress(
        "팀 평가", sum(row.completed for row in team_rows), len(team_rows)
    )
    peer_progress = EvaluationProgress(
        "개인 평가", sum(row.completed for row in peer_rows), len(peer_rows)
    )
    completed = team_progress.completed + peer_progress.completed
    expected = team_progress.expected + peer_progress.expected
    membership = getattr(participant, "team_membership", None)
    team = membership.team if membership else None
    peer_completed_ids = {row.pk for row in peer_rows if row.completed}
    members = []
    if team:
        members = [
            {
                "participant_id": member.participant_id,
                "student_number_snapshot": member.participant.student_number_snapshot,
                "display_name_snapshot": member.participant.display_name_snapshot,
                "is_self": member.participant_id == participant.pk,
                "evaluation_completed": (
                    member.participant_id == participant.pk
                    or member.participant_id in peer_completed_ids
                ),
            }
            for member in team.memberships.select_related("participant")
        ]
    pending = [
        {
            "category": "TEAM",
            "label": "팀 평가",
            "target": row.label,
            "description": row.description,
            "target_id": row.pk,
            "url_name": row.url_name,
        }
        for row in team_rows
        if not row.completed
    ] + [
        {
            "category": "PEER",
            "label": "개인 평가",
            "target": row.label,
            "description": row.description,
            "target_id": row.pk,
            "url_name": row.url_name,
        }
        for row in peer_rows
        if not row.completed
    ]
    remaining = round_obj.evaluation_end_at - timezone.now()
    return {
        "is_demo": False,
        "round": {
            "title": round_obj.title,
            "status": round_obj.get_status_display(),
            "evaluation_start_at": round_obj.evaluation_start_at,
            "evaluation_end_at": round_obj.evaluation_end_at,
            "d_day": max(ceil(remaining.total_seconds() / 86400), 0),
        },
        "team": {
            "team_number": team.team_number if team else None,
            "name": team.name if team else "팀 편성 전",
            "members": members,
        },
        "progress": {
            "team": team_progress,
            "peer": peer_progress,
            "completed": completed,
            "expected": expected,
            "percent": 100 if expected == 0 else round(completed / expected * 100),
        },
        "pending_evaluations": pending,
        "latest_result": _latest_result(user),
    }
