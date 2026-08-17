from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from reviews.models import ReviewAnswer, ReviewSubmission
from rounds.models import EvaluationRound, RoundParticipant, TemplateQuestion
from teams.models import Team


class DuplicateReviewError(ValidationError):
    pass


@dataclass(frozen=True)
class ReviewTargetRow:
    pk: int
    label: str
    description: str
    completed: bool
    url_name: str


def current_participation(user):
    return (
        RoundParticipant.objects.select_related("round", "team_membership__team")
        .filter(user=user, round__status=EvaluationRound.Status.IN_PROGRESS)
        .first()
    )


# 아래 조회 경로는 시작된 회차 전체를 다룬다. 제출(쓰기)은 여전히 진행 중 회차에서만 열린다.
REVIEWABLE_STATUSES = (
    EvaluationRound.Status.IN_PROGRESS,
    EvaluationRound.Status.COMPLETED,
)


def started_participations(user):
    """학생이 참가한 시작된 회차들 - 최신 회차가 앞에 온다."""
    return list(
        RoundParticipant.objects.select_related("round", "team_membership__team")
        .filter(user=user, round__status__in=REVIEWABLE_STATUSES)
        .order_by("-round__started_at", "-round_id")
    )


def participation_for_round(user, round_id):
    return (
        RoundParticipant.objects.select_related("round", "team_membership__team")
        .filter(user=user, round__status__in=REVIEWABLE_STATUSES, round_id=round_id)
        .first()
    )


def own_submission(user, submission_id):
    """본인이 제출한 응답만 돌려준다(PR-008). 회차는 가리지 않는다."""
    return (
        ReviewSubmission.objects.select_related(
            "round", "evaluator", "target_team", "target_participant"
        )
        .prefetch_related("answers__question")
        .filter(pk=submission_id, evaluator__user=user)
        .first()
    )


def team_targets(participant):
    if not participant or not hasattr(participant, "team_membership"):
        return []
    own_team_id = participant.team_membership.team_id
    submitted_ids = set(
        ReviewSubmission.objects.filter(
            round=participant.round,
            evaluator=participant,
            review_type=ReviewSubmission.ReviewType.TEAM,
        ).values_list("target_team_id", flat=True)
    )
    return [
        ReviewTargetRow(
            pk=team.pk,
            label=team.name,
            description=f"{team.memberships.count()}명 구성",
            completed=team.pk in submitted_ids,
            url_name="reviews:team-form",
        )
        for team in participant.round.teams.exclude(pk=own_team_id).prefetch_related("memberships")
    ]


def peer_targets(participant):
    if not participant or not hasattr(participant, "team_membership"):
        return []
    target_participants = RoundParticipant.objects.filter(
        team_membership__team=participant.team_membership.team
    ).exclude(pk=participant.pk)
    submitted_ids = set(
        ReviewSubmission.objects.filter(
            round=participant.round,
            evaluator=participant,
            review_type=ReviewSubmission.ReviewType.PEER,
        ).values_list("target_participant_id", flat=True)
    )
    return [
        ReviewTargetRow(
            pk=target.pk,
            label=target.display_name_snapshot,
            description=target.student_number_snapshot,
            completed=target.pk in submitted_ids,
            url_name="reviews:peer-form",
        )
        for target in target_participants
    ]


def review_window_state(round_obj):
    now = timezone.now()
    if now < round_obj.evaluation_start_at:
        return "BEFORE"
    if now >= round_obj.evaluation_end_at:
        return "CLOSED"
    return "OPEN"


def questions_for(round_obj, review_type):
    template = (
        round_obj.team_template
        if review_type == ReviewSubmission.ReviewType.TEAM
        else round_obj.peer_template
    )
    if not template:
        return TemplateQuestion.objects.none()
    return template.questions.all()


def get_submission(participant, review_type, target_id):
    lookup = (
        {"target_team_id": target_id}
        if review_type == "TEAM"
        else {"target_participant_id": target_id}
    )
    return (
        ReviewSubmission.objects.prefetch_related("answers__question")
        .filter(
            round=participant.round,
            evaluator=participant,
            review_type=review_type,
            **lookup,
        )
        .first()
    )


def _validate_target(participant, review_type, target_id):
    if not hasattr(participant, "team_membership"):
        raise PermissionDenied("팀에 배정되지 않았습니다.")
    if review_type == ReviewSubmission.ReviewType.TEAM:
        target = Team.objects.filter(pk=target_id, round=participant.round).first()
        if not target or target.pk == participant.team_membership.team_id:
            raise PermissionDenied("평가할 수 없는 팀입니다.")
        return {"target_team": target}
    target = RoundParticipant.objects.filter(pk=target_id, round=participant.round).first()
    if (
        not target
        or target.pk == participant.pk
        or not hasattr(target, "team_membership")
        or target.team_membership.team_id != participant.team_membership.team_id
    ):
        raise PermissionDenied("평가할 수 없는 참가자입니다.")
    return {"target_participant": target}


def submit_review(*, participant, review_type, target_id, answers):
    if participant.round.status != EvaluationRound.Status.IN_PROGRESS:
        raise ValidationError("진행 중인 회차가 아닙니다.")
    if review_window_state(participant.round) != "OPEN":
        raise ValidationError("평가 제출 기간이 아닙니다.")
    target = _validate_target(participant, review_type, target_id)
    questions = list(questions_for(participant.round, review_type))
    question_by_id = {question.pk: question for question in questions}
    if set(answers) - set(question_by_id):
        raise ValidationError("현재 질문지에 없는 문항이 포함됐습니다.")
    missing = [
        question.prompt
        for question in questions
        if question.is_required and question.pk not in answers
    ]
    if missing:
        raise ValidationError("필수 문항에 모두 답해 주세요.")
    answer_rows = []
    for question_id, value in answers.items():
        question = question_by_id[question_id]
        if question.response_type == TemplateQuestion.ResponseType.RATING_5:
            if type(value) is not int or not 1 <= value <= 5:
                raise ValidationError("점수는 1~5의 정수여야 합니다.")
            answer_rows.append((question, value, None))
        else:
            text = str(value).strip()
            if len(text) > 2000:
                raise ValidationError("서술 답변은 2,000자 이하여야 합니다.")
            answer_rows.append((question, None, text))
    try:
        with transaction.atomic():
            submission = ReviewSubmission.objects.create(
                round=participant.round,
                review_type=review_type,
                evaluator=participant,
                **target,
            )
            ReviewAnswer.objects.bulk_create(
                [
                    ReviewAnswer(
                        submission=submission,
                        question=question,
                        rating_value=rating,
                        text_value=text or "",
                    )
                    for question, rating, text in answer_rows
                ]
            )
            return submission
    except IntegrityError as error:
        if get_submission(participant, review_type, target_id):
            raise DuplicateReviewError("이미 제출한 평가입니다.") from error
        raise
