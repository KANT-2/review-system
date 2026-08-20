from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from audit.services import record_event
from notifications.models import Notification
from notifications.services import notify_users
from results.models import EvaluationResult
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
    is_create = round_obj.pk is None
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
    if is_create and selected_users:
        notify_users(
            selected_users,
            category=Notification.Category.ROUND_CREATED,
            title="새 평가 회차가 생성되었습니다",
            message=f"'{round_obj.title}' 회차가 생성되었습니다.",
        )
    return round_obj


@dataclass(frozen=True)
class RoundStartCheck:
    message: str
    # True면 확인 체크박스로 넘어갈 수 있는 경고, False면 무조건 막는 오류.
    confirmable: bool = False


def round_start_checks(round_obj):
    """회차 시작 조건을 하나씩 확인한다.

    미배정 참가자는 더 이상 시작 자체를 막지 않는다 - 그 주차에 참여 못 하는 사정이 있는
    학생이 있을 수 있어서다. 대신 확인(force_confirmed)을 받아야 하고, 그 참가자는 이번
    회차 평가·점수 계산에서 빠진다. 나머지 조건(팀 구성, 템플릿, 평가 기간)은 그대로 막는다.
    """
    checks = []
    participants = list(round_obj.participants.all())
    teams = list(round_obj.teams.prefetch_related("memberships"))
    assigned_ids = {
        membership.participant_id for team in teams for membership in team.memberships.all()
    }
    if not participants:
        checks.append(RoundStartCheck("참가자를 한 명 이상 선택해 주세요."))
    if len(teams) < 2:
        checks.append(RoundStartCheck("비어 있지 않은 팀이 2개 이상 필요합니다."))
    if any(not team.memberships.all() for team in teams):
        checks.append(RoundStartCheck("빈 팀이 있습니다."))
    unassigned = [participant for participant in participants if participant.pk not in assigned_ids]
    if unassigned:
        names = ", ".join(participant.display_name_snapshot for participant in unassigned)
        checks.append(
            RoundStartCheck(
                f"배정되지 않은 참가자가 있습니다: {names}. 확인하고 시작하면 이 참가자들은 "
                "이번 회차 평가·점수 계산에서 빠집니다.",
                confirmable=True,
            )
        )
    for label, template in (
        ("팀 평가", round_obj.team_template),
        ("개인 평가", round_obj.peer_template),
    ):
        if template is None:
            checks.append(RoundStartCheck(f"{label} 템플릿을 선택해 주세요."))
        elif not template.questions.filter(
            response_type=TemplateQuestion.ResponseType.RATING_5
        ).exists():
            checks.append(RoundStartCheck(f"{label} 템플릿에 1~5점 문항이 필요합니다."))
    if round_obj.evaluation_start_at >= round_obj.evaluation_end_at:
        checks.append(RoundStartCheck("평가 기간을 확인해 주세요."))
    return checks


def round_start_errors(round_obj):
    """메시지 문자열만 필요한 곳에서 쓰는 하위 호환 헬퍼."""
    return [check.message for check in round_start_checks(round_obj)]


@transaction.atomic
def start_round(*, round_id, actor, force_confirmed=False):
    round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
    if round_obj.status != EvaluationRound.Status.DRAFT:
        raise ValidationError("준비 중인 회차만 시작할 수 있습니다.")
    checks = round_start_checks(round_obj)
    blocking = [check.message for check in checks if not check.confirmable]
    if blocking:
        raise ValidationError(blocking)
    confirmable = [check.message for check in checks if check.confirmable]
    if confirmable and not force_confirmed:
        raise ValidationError(confirmable)
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


def participant_progress_rows(round_obj):
    """회차 참가자별 팀·개인 평가 제출 현황을 반환한다."""
    team_count = round_obj.teams.count()
    completed = (
        ReviewSubmission.objects.filter(round=round_obj)
        .values("evaluator_id", "review_type")
        .annotate(count=Count("id"))
    )
    completed_map = {(row["evaluator_id"], row["review_type"]): row["count"] for row in completed}
    rows = []
    participants = round_obj.participants.select_related("team_membership__team", "user").all()
    for participant in participants:
        team_size = (
            participant.team_membership.team.memberships.count()
            if hasattr(participant, "team_membership")
            else 0
        )
        team_expected = max(team_count - 1, 0)
        peer_expected = max(team_size - 1, 0)
        rows.append(
            {
                "participant": participant,
                "team_expected": team_expected,
                "team_completed": completed_map.get(
                    (participant.pk, ReviewSubmission.ReviewType.TEAM), 0
                ),
                "peer_expected": peer_expected,
                "peer_completed": completed_map.get(
                    (participant.pk, ReviewSubmission.ReviewType.PEER), 0
                ),
            }
        )
    return rows


def is_participant_complete(participant):
    """이 참가자 한 명만 팀·개인 평가를 다 제출했는지 확인한다.

    participant_progress_rows는 회차 전체를 훑어야 해서, 제출 한 건마다 완료 여부만
    가볍게 확인하려는 곳(예: 완료 알림)에는 이 쪽이 낫다.
    """
    if not hasattr(participant, "team_membership"):
        return False
    round_obj = participant.round
    team_expected = max(round_obj.teams.count() - 1, 0)
    peer_expected = max(participant.team_membership.team.memberships.count() - 1, 0)
    team_completed = ReviewSubmission.objects.filter(
        round=round_obj, evaluator=participant, review_type=ReviewSubmission.ReviewType.TEAM
    ).count()
    peer_completed = ReviewSubmission.objects.filter(
        round=round_obj, evaluator=participant, review_type=ReviewSubmission.ReviewType.PEER
    ).count()
    return team_completed == team_expected and peer_completed == peer_expected


def pending_participant_rows(round_obj):
    """팀·개인 평가 중 하나라도 덜 제출한 참가자 행만 반환한다."""
    return [
        row
        for row in participant_progress_rows(round_obj)
        if row["team_completed"] < row["team_expected"]
        or row["peer_completed"] < row["peer_expected"]
    ]


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
    notify_users(
        (participant.user for participant in round_obj.participants.select_related("user")),
        category=Notification.Category.ROUND_COMPLETED,
        title="평가가 종료되었습니다",
        message=f"'{round_obj.title}' 회차 평가가 종료되었습니다.",
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
    """템플릿 목록 화면용 - 문항 수, 사용 중(잠금) 여부, 복제본 유무를 함께 계산한다.

    보관된 템플릿이 맨 아래로 가도록 정렬한다 - 안 쓸 템플릿이지만 존재는 알 수 있어야
    한다("전체"/"보관됨" 탭 구분은 뷰에서 이 목록을 다시 걸러 쓴다). 보관된 행에는
    왜 못 지우는지 보여줄 round_titles를 같이 채운다.
    """
    templates = (
        QuestionTemplate.objects.annotate(
            question_count=Count("questions", distinct=True),
            copy_count=Count("copies", distinct=True),
        )
        .select_related("created_by", "archived_by")
        .order_by("is_archived", "category", "name")
    )
    rows = []
    for template in templates:
        template.locked = template.is_locked
        template.has_copies = template.copy_count > 0
        if template.is_archived:
            template.round_titles = template.rounds_in_use()
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
            competency=question.competency,
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
def archive_question_template(*, template_id, actor):
    """지울 수 없는(잠긴) 템플릿을 목록/새 회차 선택지에서 치운다.

    save()가 잠긴 템플릿의 변경 자체를 막기 때문에 인스턴스를 고쳐 save()를 부르지 않고
    쿼리셋 update로 우회한다 - 내용은 그대로 두고 상태만 바꾸는 것이라 잠금 목적과
    충돌하지 않는다.
    """
    template = QuestionTemplate.objects.get(pk=template_id)
    if not template.is_locked:
        raise ValidationError("사용 중이지 않은 템플릿은 보관 대신 삭제해 주세요.")
    if template.is_archived:
        return template
    QuestionTemplate.objects.filter(pk=template_id).update(
        is_archived=True, archived_at=timezone.now(), archived_by=actor
    )
    record_event(
        action="QUESTION_TEMPLATE_ARCHIVED",
        target=template,
        actor=actor,
        summary={"name": template.name, "category": template.category},
    )
    template.refresh_from_db()
    return template


@transaction.atomic
def restore_question_template(*, template_id, actor):
    template = QuestionTemplate.objects.get(pk=template_id)
    if not template.is_archived:
        return template
    QuestionTemplate.objects.filter(pk=template_id).update(
        is_archived=False, archived_at=None, archived_by=None
    )
    record_event(
        action="QUESTION_TEMPLATE_RESTORED",
        target=template,
        actor=actor,
        summary={"name": template.name, "category": template.category},
    )
    template.refresh_from_db()
    return template


@transaction.atomic
def delete_question_template(*, template_id, actor):
    template = QuestionTemplate.objects.get(pk=template_id)
    if template.is_locked:
        raise ValidationError("시작된 회차가 사용하는 템플릿은 삭제할 수 없습니다.")
    if template.team_rounds.exists() or template.peer_rounds.exists():
        raise ValidationError("준비 중인 회차가 사용하고 있어 삭제할 수 없습니다.")
    # copied_from은 복제 계보를 남기는 PROTECT FK다(docs/DATABASE-DESIGN.md). 원본을 그냥
    # 지우면 DB가 막아 500이 나므로, 화면에서 무엇을 먼저 지워야 하는지 알려준다.
    if template.copies.exists():
        raise ValidationError(
            "이 템플릿을 복제한 템플릿이 있어 삭제할 수 없습니다. 복제본을 먼저 삭제해 주세요."
        )
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
    """회차를 지운다 - 준비 중(DRAFT)이거나 완료(COMPLETED)된 회차만 대상이다.

    진행 중(IN_PROGRESS) 회차는 실시간으로 쓰이고 있어 지우지 않는다(먼저 마감하거나
    준비 중으로 되돌려야 한다).

    완료된 회차는 채점 결과·평가 제출·튜터 개인/팀평가·감사 로그까지 팀·참가자·회차를
    PROTECT로 참조하고 있어서, 그 역순(자식 -> 부모)으로 하나씩 정리해야 삭제 시
    ProtectedError 없이 끝까지 지워진다. 감사 로그(AuditEvent)는 내용은 남기고
    round만 비워서(nullable) 회차 삭제 뒤에도 "누가 언제 무엇을 했는지" 기록 자체는
    보존한다.
    """
    round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
    if round_obj.status == EvaluationRound.Status.IN_PROGRESS:
        raise ValidationError(
            "진행 중인 회차는 삭제할 수 없습니다. 먼저 마감하거나 준비 중으로 되돌려 주세요."
        )
    record_event(
        action="ROUND_DELETED",
        target=round_obj,
        actor=actor,
        summary={"title": round_obj.title, "participant_count": round_obj.participants.count()},
    )

    EvaluationResult.objects.filter(calculation_run__round=round_obj).delete()
    round_obj.calculation_runs.all().delete()
    round_obj.review_final_submissions.all().delete()
    round_obj.review_submissions.all().delete()
    round_obj.tutor_team_reviews.all().delete()
    round_obj.tutor_reviews.all().delete()
    round_obj.audit_events.update(round=None)
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
    if round_obj.tutor_reviews.exists() or round_obj.tutor_team_reviews.exists():
        raise ValidationError(
            "이미 작성된 튜터 평가가 있어 되돌릴 수 없습니다. 마감 후 채점해 주세요."
        )
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
