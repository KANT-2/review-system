from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from notifications.services import notify_users
from reviews.models import (
    ReviewAnswer,
    ReviewFinalSubmission,
    ReviewSubmission,
    TutorReview,
    TutorReviewAnswer,
    TutorTeamReview,
    TutorTeamReviewAnswer,
)
from rounds.models import EvaluationRound, RoundParticipant, TemplateQuestion
from rounds.services import is_participant_complete
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
    # 건별 확정 여부 - 지금은 개인 평가에서만 쓴다. 다른 호출부(팀 평가, 튜터 평가)는
    # 기본값 False로 그대로 두면 되므로 이 필드를 몰라도 된다.
    locked: bool = False


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
    peer_submissions = ReviewSubmission.objects.filter(
        round=participant.round,
        evaluator=participant,
        review_type=ReviewSubmission.ReviewType.PEER,
    ).values_list("target_participant_id", "locked_at")
    submitted_ids = set()
    locked_ids = set()
    for target_id, locked_at in peer_submissions:
        submitted_ids.add(target_id)
        if locked_at is not None:
            locked_ids.add(target_id)
    return [
        ReviewTargetRow(
            pk=target.pk,
            label=target.display_name_snapshot,
            description=target.student_number_snapshot,
            completed=target.pk in submitted_ids,
            url_name="reviews:peer-form",
            locked=target.pk in locked_ids,
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


def is_final_submitted(participant, review_type):
    """해당 유형의 평가를 최종 제출했는지. 최종 제출 뒤에는 수정할 수 없다."""
    if participant is None:
        return False
    return ReviewFinalSubmission.objects.filter(
        round=participant.round, evaluator=participant, review_type=review_type
    ).exists()


def final_submit_state(participant, review_type):
    """목록 화면이 최종 제출 영역을 그리는 데 쓰는 상태 묶음."""
    targets = team_targets(participant) if review_type == "TEAM" else peer_targets(participant)
    completed = sum(target.completed for target in targets)
    finalized = is_final_submitted(participant, review_type)
    return {
        "finalized": finalized,
        "completed": completed,
        "total": len(targets),
        "remaining": len(targets) - completed,
        # 대상이 없는 경우(1인 팀 등)도 최종 제출로 마무리할 수 있어야 한다.
        "can_finalize": (
            not finalized
            and completed == len(targets)
            and participant is not None
            and participant.round.status == EvaluationRound.Status.IN_PROGRESS
            and review_window_state(participant.round) == "OPEN"
        ),
    }


def final_submit(*, participant, review_type):
    """유형별 최종 제출. 되돌릴 수 없으므로 서버에서 조건을 다시 확인한다."""
    state = final_submit_state(participant, review_type)
    if state["finalized"]:
        raise ValidationError("이미 최종 제출했습니다.")
    if not state["can_finalize"]:
        raise ValidationError("모든 대상을 제출해야 최종 제출할 수 있습니다.")
    try:
        return ReviewFinalSubmission.objects.create(
            round=participant.round, evaluator=participant, review_type=review_type
        )
    except IntegrityError as error:
        raise ValidationError("이미 최종 제출했습니다.") from error


def _get_or_create_submission(participant, review_type, target):
    existing = ReviewSubmission.objects.filter(
        round=participant.round, evaluator=participant, review_type=review_type, **target
    ).first()
    if existing:
        return existing
    try:
        # 동시 요청이 겹쳐도 유니크 제약이 한 건만 남긴다(TR-007, PR-009).
        with transaction.atomic():
            return ReviewSubmission.objects.create(
                round=participant.round,
                review_type=review_type,
                evaluator=participant,
                **target,
            )
    except IntegrityError:
        return ReviewSubmission.objects.get(
            round=participant.round, evaluator=participant, review_type=review_type, **target
        )


def validated_answer_rows(questions, answers):
    """제출된 답변을 문항 정의와 대조해 (문항, 점수, 서술) 목록으로 만든다.

    학생 평가와 튜터 평가가 같은 질문지를 쓰므로 검증도 한곳에서 한다. 화면에서 막았더라도
    직접 POST하는 경로가 남아 있어 서버에서 다시 확인한다.
    """
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
    return answer_rows


def submit_review(*, participant, review_type, target_id, answers):
    if participant.round.status != EvaluationRound.Status.IN_PROGRESS:
        raise ValidationError("진행 중인 회차가 아닙니다.")
    if review_window_state(participant.round) != "OPEN":
        raise ValidationError("평가 제출 기간이 아닙니다.")
    if is_final_submitted(participant, review_type):
        raise ValidationError("최종 제출한 평가는 수정할 수 없습니다.")
    existing = get_submission(participant, review_type, target_id)
    if existing is not None and existing.locked_at is not None:
        raise ValidationError("확정된 평가는 수정할 수 없습니다.")
    target = _validate_target(participant, review_type, target_id)
    questions = list(questions_for(participant.round, review_type))
    answer_rows = validated_answer_rows(questions, answers)
    was_complete = is_participant_complete(participant)
    with transaction.atomic():
        # 최종 제출 전이면 다시 저장할 수 있다 - 기존 답변을 지우고 새로 쓴다.
        submission = _get_or_create_submission(participant, review_type, target)
        submission.answers.all().delete()
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
    if not was_complete and is_participant_complete(participant):
        _notify_tutors_of_completion(participant)
    return submission


def _notify_tutors_of_completion(participant):
    notify_users(
        User.objects.filter(role__in=[User.Role.TUTOR, User.Role.ADMIN], is_active=True),
        category=Notification.Category.PARTICIPANT_COMPLETED,
        title="학생이 평가를 모두 제출했습니다",
        message=(
            f"{participant.display_name_snapshot}님이 "
            f"'{participant.round.title}' 팀·개인 평가를 모두 제출했습니다."
        ),
        link=reverse("rounds:reviews", kwargs={"round_id": participant.round_id}),
    )


def lock_submission(*, participant, review_type, target_id):
    """대상 한 건만 확정해서 더 이상 못 고치게 한다(TR-010에 준하는 건별 확정).

    유형 전체를 잠그는 final_submit()과는 별개다 - 지금은 개인 평가 카드에서만 쓴다.
    """
    if participant.round.status != EvaluationRound.Status.IN_PROGRESS:
        raise ValidationError("진행 중인 회차가 아닙니다.")
    if review_window_state(participant.round) != "OPEN":
        raise ValidationError("평가 제출 기간이 아닙니다.")
    if is_final_submitted(participant, review_type):
        raise ValidationError("이미 유형 전체가 최종 제출되어 있습니다.")
    existing = get_submission(participant, review_type, target_id)
    if existing is None:
        raise ValidationError("먼저 평가를 제출해야 확정할 수 있습니다.")
    if existing.locked_at is not None:
        raise ValidationError("이미 확정된 평가입니다.")
    existing.locked_at = timezone.now()
    existing.save(update_fields=["locked_at"])
    return existing


# --- 튜터 개인평가 -------------------------------------------------------------
# 학생끼리 하는 개인 평가와 달리 제출 기간·최종 제출 개념이 없다. 참가자와 질문지가 동결된
# 뒤(회차 시작 이후)에만 쓸 수 있고, 점수는 아직 최종점수 계산에 반영하지 않는다.


def tutor_reviewable(round_obj):
    """튜터가 이 회차에 개인평가를 쓸 수 있는지. 준비 중(DRAFT) 회차는 질문지가 바뀔 수 있다."""
    return round_obj.status != EvaluationRound.Status.DRAFT


def tutor_review_targets(round_obj, tutor):
    """회차 참가자 전원 - 튜터가 이미 쓴 대상은 completed로 표시한다."""
    written_ids = set(
        TutorReview.objects.filter(round=round_obj, evaluator=tutor).values_list(
            "target_participant_id", flat=True
        )
    )
    return [
        ReviewTargetRow(
            pk=participant.pk,
            label=participant.display_name_snapshot,
            description=(
                f"{participant.student_number_snapshot} · {participant.team_membership.team.name}"
                if hasattr(participant, "team_membership")
                else f"{participant.student_number_snapshot} · 팀 미배정"
            ),
            completed=participant.pk in written_ids,
            url_name="rounds:tutor-review-form",
        )
        for participant in round_obj.participants.select_related("team_membership__team").all()
    ]


def get_tutor_review(round_obj, tutor, participant_id):
    return (
        TutorReview.objects.prefetch_related("answers__question")
        .filter(round=round_obj, evaluator=tutor, target_participant_id=participant_id)
        .first()
    )


def tutor_review_questions(round_obj):
    """튜터 개인평가도 그 회차의 개인 평가 질문지를 그대로 쓴다."""
    return questions_for(round_obj, ReviewSubmission.ReviewType.PEER)


def submit_tutor_review(*, round_obj, tutor, participant_id, answers):
    if not tutor_reviewable(round_obj):
        raise ValidationError("회차를 시작한 뒤에 평가할 수 있습니다.")
    participant = RoundParticipant.objects.filter(pk=participant_id, round=round_obj).first()
    if not participant:
        raise PermissionDenied("이 회차의 수강생이 아닙니다.")
    questions = list(tutor_review_questions(round_obj))
    if not questions:
        raise ValidationError("이 회차에 개인 평가 질문지가 없습니다.")
    answer_rows = validated_answer_rows(questions, answers)
    with transaction.atomic():
        review, _ = TutorReview.objects.get_or_create(
            round=round_obj, evaluator=tutor, target_participant=participant
        )
        # 다시 쓰면 기존 답변을 지우고 새로 넣는다 - 학생 평가의 재저장과 같은 방식이다.
        review.answers.all().delete()
        TutorReviewAnswer.objects.bulk_create(
            [
                TutorReviewAnswer(
                    review=review,
                    question=question,
                    rating_value=rating,
                    text_value=text or "",
                )
                for question, rating, text in answer_rows
            ]
        )
        return review


# --- 튜터 팀평가 ---------------------------------------------------------------
# 튜터 개인평가와 짝을 이루는 팀 단위 버전. 대상이 참가자가 아니라 팀이라는 점만 다르고
# 나머지 규칙(회차 시작 후에만, 다시 쓰면 덮어씀)은 동일하다.


def tutor_team_review_targets(round_obj, tutor):
    """회차의 팀 전체 - 튜터가 이미 쓴 팀은 completed로 표시한다."""
    written_ids = set(
        TutorTeamReview.objects.filter(round=round_obj, evaluator=tutor).values_list(
            "target_team_id", flat=True
        )
    )
    return [
        ReviewTargetRow(
            pk=team.pk,
            label=team.name,
            description=f"{team.memberships.count()}명 구성",
            completed=team.pk in written_ids,
            url_name="rounds:tutor-team-review-form",
        )
        for team in round_obj.teams.prefetch_related("memberships")
    ]


def get_tutor_team_review(round_obj, tutor, team_id):
    return (
        TutorTeamReview.objects.prefetch_related("answers__question")
        .filter(round=round_obj, evaluator=tutor, target_team_id=team_id)
        .first()
    )


def tutor_team_review_questions(round_obj):
    """튜터 팀평가도 그 회차의 팀 평가 질문지를 그대로 쓴다."""
    return questions_for(round_obj, ReviewSubmission.ReviewType.TEAM)


def submit_tutor_team_review(*, round_obj, tutor, team_id, answers):
    if not tutor_reviewable(round_obj):
        raise ValidationError("회차를 시작한 뒤에 평가할 수 있습니다.")
    team = Team.objects.filter(pk=team_id, round=round_obj).first()
    if not team:
        raise PermissionDenied("이 회차의 팀이 아닙니다.")
    questions = list(tutor_team_review_questions(round_obj))
    if not questions:
        raise ValidationError("이 회차에 팀 평가 질문지가 없습니다.")
    answer_rows = validated_answer_rows(questions, answers)
    with transaction.atomic():
        review, _ = TutorTeamReview.objects.get_or_create(
            round=round_obj, evaluator=tutor, target_team=team
        )
        review.answers.all().delete()
        TutorTeamReviewAnswer.objects.bulk_create(
            [
                TutorTeamReviewAnswer(
                    review=review,
                    question=question,
                    rating_value=rating,
                    text_value=text or "",
                )
                for question, rating, text in answer_rows
            ]
        )
        return review


def tutor_review_progress(round_obj, tutor):
    """대시보드용 - 이 튜터가 이번 회차에서 실제로 작성한 팀/개인 평가 진행률."""
    return {
        "team_completed": TutorTeamReview.objects.filter(round=round_obj, evaluator=tutor).count(),
        "team_expected": round_obj.teams.count(),
        "peer_completed": TutorReview.objects.filter(round=round_obj, evaluator=tutor).count(),
        "peer_expected": round_obj.participants.count(),
    }
