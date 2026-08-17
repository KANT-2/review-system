from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from audit.services import record_event
from reviews.models import ReviewSubmission
from rounds.models import EvaluationRound, RoundParticipant, TemplateQuestion


@dataclass(frozen=True)
class ReviewProgress:
    team_expected: int
    team_completed: int
    peer_expected: int
    peer_completed: int

    @property
    def missing_count(self):
        return (self.team_expected - self.team_completed) + (
            self.peer_expected - self.peer_completed
        )


def participant_snapshot_values(user):
    return {
        "student_number_snapshot": user.student_number or f"U{user.pk:06d}",
        "display_name_snapshot": user.first_name.strip() or user.email,
    }


@transaction.atomic
def save_round(*, form, actor):
    round_obj = form.save(commit=False)
    if round_obj.pk:
        current = EvaluationRound.objects.select_for_update().get(pk=round_obj.pk)
        if current.status != EvaluationRound.Status.DRAFT:
            raise ValidationError("시작된 회차는 수정할 수 없습니다.")
    else:
        round_obj.created_by = actor
    round_obj.full_clean()
    round_obj.save()

    selected_users = list(form.cleaned_data["participants"])
    selected_ids = {user.pk for user in selected_users}
    round_obj.participants.exclude(user_id__in=selected_ids).delete()
    existing = {participant.user_id: participant for participant in round_obj.participants.all()}
    for user in selected_users:
        values = participant_snapshot_values(user)
        participant = existing.get(user.pk)
        if participant:
            for field, value in values.items():
                setattr(participant, field, value)
            participant.save(update_fields=(*values.keys(),))
        else:
            RoundParticipant.objects.create(round=round_obj, user=user, **values)
    return round_obj


def round_start_errors(round_obj):
    errors = []
    participants = list(round_obj.participants.all())
    teams = list(round_obj.teams.prefetch_related("memberships"))
    assigned_ids = [
        membership.participant_id for team in teams for membership in team.memberships.all()
    ]
    if not participants:
        errors.append("참가자를 한 명 이상 선택해 주세요.")
    if len(teams) < 2:
        errors.append("비어 있지 않은 팀이 2개 이상 필요합니다.")
    if any(not team.memberships.all() for team in teams):
        errors.append("빈 팀이 있습니다.")
    if sorted(assigned_ids) != sorted(participant.pk for participant in participants):
        errors.append("모든 참가자를 정확히 한 팀에 배정해 주세요.")
    for label, template in (
        ("팀 평가", round_obj.team_template),
        ("개인 평가", round_obj.peer_template),
    ):
        if template is None:
            errors.append(f"{label} 템플릿을 선택해 주세요.")
        elif not template.questions.filter(
            response_type=TemplateQuestion.ResponseType.RATING_5
        ).exists():
            errors.append(f"{label} 템플릿에 1~5점 문항이 필요합니다.")
    if round_obj.evaluation_start_at >= round_obj.evaluation_end_at:
        errors.append("평가 기간을 확인해 주세요.")
    return errors


@transaction.atomic
def start_round(*, round_id, actor):
    round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
    if round_obj.status != EvaluationRound.Status.DRAFT:
        raise ValidationError("준비 중인 회차만 시작할 수 있습니다.")
    errors = round_start_errors(round_obj)
    if errors:
        raise ValidationError(errors)
    for participant in round_obj.participants.select_related("user"):
        values = participant_snapshot_values(participant.user)
        for field, value in values.items():
            setattr(participant, field, value)
        participant.save(update_fields=(*values.keys(),))
    round_obj.status = EvaluationRound.Status.IN_PROGRESS
    round_obj.started_at = timezone.now()
    try:
        round_obj.save(update_fields=("status", "started_at", "updated_at"))
    except IntegrityError as error:
        raise ValidationError("이미 진행 중인 다른 회차가 있습니다.") from error
    record_event(
        action="ROUND_STARTED",
        target=round_obj,
        actor=actor,
        round_obj=round_obj,
        summary={"participant_count": round_obj.participants.count()},
    )
    return round_obj


def get_review_progress(round_obj):
    team_sizes = list(
        round_obj.teams.annotate(size=Count("memberships")).values_list("size", flat=True)
    )
    participant_count = round_obj.participants.count()
    team_expected = sum(participant_count - size for size in team_sizes)
    peer_expected = sum(size * (size - 1) for size in team_sizes)
    completed = round_obj.review_submissions.values("review_type").annotate(count=Count("id"))
    counts = {row["review_type"]: row["count"] for row in completed}
    return ReviewProgress(
        team_expected=team_expected,
        team_completed=counts.get(ReviewSubmission.ReviewType.TEAM, 0),
        peer_expected=peer_expected,
        peer_completed=counts.get(ReviewSubmission.ReviewType.PEER, 0),
    )


@transaction.atomic
def complete_round(*, round_id, actor, force_confirmed=False):
    round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
    if round_obj.status != EvaluationRound.Status.IN_PROGRESS:
        raise ValidationError("진행 중인 회차만 마감할 수 있습니다.")
    progress = get_review_progress(round_obj)
    if progress.missing_count and not force_confirmed:
        raise ValidationError("미제출 평가가 있어 강제 마감 확인이 필요합니다.")
    round_obj.status = EvaluationRound.Status.COMPLETED
    round_obj.completed_at = timezone.now()
    round_obj.save(update_fields=("status", "completed_at", "updated_at"))
    record_event(
        action="ROUND_FORCE_COMPLETED" if progress.missing_count else "ROUND_COMPLETED",
        target=round_obj,
        actor=actor,
        round_obj=round_obj,
        summary={"missing_count": progress.missing_count, "confirmed": bool(force_confirmed)},
    )
    return round_obj


def rounds_dashboard_rows():
    return EvaluationRound.objects.annotate(
        participant_count=Count("participants", distinct=True),
        team_count=Count("teams", distinct=True),
        submission_count=Count("review_submissions", distinct=True),
        active_runs=Count("calculation_runs", filter=Q(calculation_runs__is_active=True)),
    )
