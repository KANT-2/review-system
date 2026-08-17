from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from audit.services import record_event
from reviews.models import ReviewSubmission
from rounds.models import (
    EvaluationRound,
    QuestionTemplate,
    RoundParticipant,
    TemplateQuestion,
)


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
        # 다시 열기 가능 여부는 활성 여부와 무관하게 "채점 기록이 있었는지"로 판단한다.
        run_count=Count("calculation_runs", distinct=True),
    )


def question_template_rows():
    """템플릿 목록 화면용 - 문항 수와 사용 중(잠금) 여부를 함께 계산한다."""
    templates = (
        QuestionTemplate.objects.annotate(question_count=Count("questions"))
        .select_related("created_by")
        .order_by("category", "name")
    )
    rows = []
    for template in templates:
        template.locked = template.is_locked
        rows.append(template)
    return rows


@transaction.atomic
def save_question_template(*, form, formset, actor):
    """템플릿과 문항을 함께 저장한다.

    시작된 회차가 사용 중인 템플릿은 잠긴다(QuestionTemplate.is_locked) - 이미 제출된 평가의
    문항이 바뀌면 안 되기 때문이다. 문항 순서는 화면에 나온 순서대로 다시 매긴다.
    """
    template = form.instance
    if template.pk and template.is_locked:
        raise ValidationError("시작된 회차가 사용하는 템플릿은 수정할 수 없습니다.")
    is_new = template.pk is None
    if is_new:
        template.created_by = actor
    template = form.save()

    formset.instance = template
    kept = [
        question_form.instance
        for question_form in formset.forms
        if question_form.cleaned_data
        and not question_form.cleaned_data.get("DELETE")
        and question_form.cleaned_data.get("prompt")
    ]
    template.questions.exclude(pk__in=[q.pk for q in kept if q.pk]).delete()
    # (template, display_order) 유니크 제약 때문에 임시 번호를 한 번 거쳐 다시 매긴다.
    for order, question in enumerate(kept, start=1):
        question.template = template
        question.display_order = 1000 + order
        question.save()
    for order, question in enumerate(kept, start=1):
        question.display_order = order
        question.save(update_fields=("display_order",))

    record_event(
        action="QUESTION_TEMPLATE_CREATED" if is_new else "QUESTION_TEMPLATE_UPDATED",
        target=template,
        actor=actor,
        summary={"category": template.category, "question_count": len(kept)},
    )
    return template


@transaction.atomic
def copy_question_template(*, template_id, actor):
    """기존 템플릿을 문항까지 복제한다 - 잠긴 템플릿도 복제는 할 수 있다."""
    source = QuestionTemplate.objects.get(pk=template_id)
    copy = QuestionTemplate.objects.create(
        name=f"{source.name} (사본)"[:100],
        description=source.description,
        category=source.category,
        copied_from=source,
        created_by=actor,
    )
    for question in source.questions.all():
        TemplateQuestion.objects.create(
            template=copy,
            response_type=question.response_type,
            prompt=question.prompt,
            is_required=question.is_required,
            display_order=question.display_order,
        )
    record_event(
        action="QUESTION_TEMPLATE_COPIED",
        target=copy,
        actor=actor,
        summary={"source_id": source.pk, "question_count": copy.questions.count()},
    )
    return copy


@transaction.atomic
def delete_question_template(*, template_id, actor):
    template = QuestionTemplate.objects.get(pk=template_id)
    if template.is_locked:
        raise ValidationError("시작된 회차가 사용하는 템플릿은 삭제할 수 없습니다.")
    if template.team_rounds.exists() or template.peer_rounds.exists():
        raise ValidationError("준비 중인 회차가 사용하고 있어 삭제할 수 없습니다.")
    record_event(
        action="QUESTION_TEMPLATE_DELETED",
        target=template,
        actor=actor,
        summary={"name": template.name, "category": template.category},
    )
    template.questions.all().delete()
    template.delete()


@transaction.atomic
def delete_round(*, round_id, actor):
    """준비 중인 회차를 지운다.

    시작된 회차는 참가자 스냅샷이 동결되고 제출·채점이 붙기 때문에 지울 수 없다. 준비 중
    회차는 팀·구성원·참가자를 함께 정리해야 지워진다(모두 PROTECT로 묶여 있다).
    """
    round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
    if round_obj.status != EvaluationRound.Status.DRAFT:
        raise ValidationError("준비 중인 회차만 삭제할 수 있습니다.")
    if round_obj.review_submissions.exists() or round_obj.calculation_runs.exists():
        raise ValidationError("제출이나 채점 기록이 있는 회차는 삭제할 수 없습니다.")
    record_event(
        action="ROUND_DELETED",
        target=round_obj,
        actor=actor,
        summary={"title": round_obj.title, "participant_count": round_obj.participants.count()},
    )
    for team in round_obj.teams.all():
        team.memberships.all().delete()
    round_obj.teams.all().delete()
    round_obj.participants.all().delete()
    round_obj.delete()


@transaction.atomic
def revert_round_to_draft(*, round_id, actor):
    """잘못 시작한 회차를 준비 중으로 되돌린다.

    제출이 하나라도 있으면 되돌리지 않는다 - 참가자·팀 구성이 다시 열리면 이미 받은 평가의
    전제가 깨진다. 이때는 마감 후 채점으로 처리해야 한다.
    """
    round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
    if round_obj.status != EvaluationRound.Status.IN_PROGRESS:
        raise ValidationError("진행 중인 회차만 되돌릴 수 있습니다.")
    if round_obj.review_submissions.exists():
        raise ValidationError("이미 제출된 평가가 있어 되돌릴 수 없습니다. 마감 후 채점해 주세요.")
    round_obj.status = EvaluationRound.Status.DRAFT
    round_obj.started_at = None
    round_obj.save(update_fields=("status", "started_at", "updated_at"))
    record_event(
        action="ROUND_REVERTED_TO_DRAFT",
        target=round_obj,
        actor=actor,
        round_obj=round_obj,
        summary={"title": round_obj.title},
    )
    return round_obj


@transaction.atomic
def reopen_round(*, round_id, actor):
    """잘못 마감한 회차를 다시 진행 중으로 되돌린다.

    이미 채점한 회차는 결과가 나가 있으므로 열지 않는다(재채점으로 처리한다). 진행 중 회차는
    전체에서 하나만 허용되므로 다른 회차가 진행 중이면 열 수 없다.
    """
    round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
    if round_obj.status != EvaluationRound.Status.COMPLETED:
        raise ValidationError("마감된 회차만 다시 열 수 있습니다.")
    if round_obj.calculation_runs.exists():
        raise ValidationError(
            "채점 기록이 있는 회차는 다시 열 수 없습니다. 재채점을 사용해 주세요."
        )
    round_obj.status = EvaluationRound.Status.IN_PROGRESS
    round_obj.completed_at = None
    try:
        round_obj.save(update_fields=("status", "completed_at", "updated_at"))
    except IntegrityError as error:
        raise ValidationError("이미 진행 중인 다른 회차가 있습니다.") from error
    record_event(
        action="ROUND_REOPENED",
        target=round_obj,
        actor=actor,
        round_obj=round_obj,
        summary={"title": round_obj.title},
    )
    return round_obj
