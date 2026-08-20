from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.services import record_event
from notifications.models import Notification
from notifications.services import announce
from results.models import CalculationRun, EvaluationResult, TutorNote
from results.services import (
    FORMULA_VERSION,
    calculate_coverage,
    calculate_final_score,
    calculate_peer_score,
    calculate_team_score,
    competition_rank,
    compute_input_digest,
    determine_data_status,
    round_to_display,
)
from reviews.models import ReviewSubmission, TutorReviewAnswer, TutorTeamReviewAnswer
from rounds.models import EvaluationRound

# toggle_publication이 "한 번 더 확인이 필요하다"고 알릴 때 쓰는 ValidationError code.
PARTIAL_CONFIRMATION_REQUIRED = "partial_confirmation_required"

# results_tutor_note.body 컬럼과 같은 상한.
TUTOR_NOTE_MAX_LENGTH = 1000

PUBLICATION_FIELDS = {
    "team_winner": "winner_published_at",
    "team_ranking": "team_ranking_published_at",
    "my_score": "my_score_published_at",
    "peer_ranking": "peer_ranking_published_at",
}


def _rating_sets(submissions):
    return [
        [answer.rating_value for answer in submission.answers.all() if answer.rating_value]
        for submission in submissions
    ]


def _rank_rows(rows, score_key, rank_key):
    scored = [row for row in rows if row[score_key] is not None]
    scored.sort(key=lambda row: round_to_display(row[score_key]), reverse=True)
    display_values = [round_to_display(row[score_key]) for row in scored]
    for row, rank in zip(scored, competition_rank(display_values), strict=True):
        row[rank_key] = rank


def _tutor_answer_sets(round_obj):
    """참가자 ID -> 이 회차에 받은 튜터 평가 제출별 평점 목록 (peer_submissions와 같은 모양).

    튜터 여러 명이 같은 학생에게 각각 TutorReview를 남길 수 있어(reviews_tutor_review_target_unique는
    (round, evaluator, target_participant) 기준), 제출 단위로 묶어 calculate_peer_score와 같은
    평균-의-평균 산식을 그대로 재사용한다.
    """
    rows = TutorReviewAnswer.objects.filter(
        review__round=round_obj, rating_value__isnull=False
    ).values_list("review__target_participant_id", "review_id", "rating_value")
    per_submission = defaultdict(list)
    for participant_id, review_id, rating_value in rows:
        per_submission[(participant_id, review_id)].append(rating_value)
    sets_by_participant = defaultdict(list)
    for (participant_id, _review_id), values in per_submission.items():
        sets_by_participant[participant_id].append(values)
    return sets_by_participant


def _tutor_team_answer_sets(round_obj):
    """팀 ID -> 이 회차에 받은 튜터 팀평가 제출별 평점 목록 (_tutor_answer_sets의 팀 버전).

    team_score는 이미 '받은 모든 평가를 동일 가중치로 평균'하는 구조라(calculate_team_score),
    튜터의 팀평가도 학생 팀평가와 같은 리스트에 한 건 더 추가하는 방식으로 섞는다.
    """
    rows = TutorTeamReviewAnswer.objects.filter(
        review__round=round_obj, rating_value__isnull=False
    ).values_list("review__target_team_id", "review_id", "rating_value")
    per_submission = defaultdict(list)
    for team_id, review_id, rating_value in rows:
        per_submission[(team_id, review_id)].append(rating_value)
    sets_by_team = defaultdict(list)
    for (team_id, _review_id), values in per_submission.items():
        sets_by_team[team_id].append(values)
    return sets_by_team


def _build_result_rows(round_obj):
    submissions = list(ReviewSubmission.objects.filter(round=round_obj).prefetch_related("answers"))
    tutor_sets_by_participant = (
        _tutor_answer_sets(round_obj) if round_obj.tutor_score_weight > 0 else defaultdict(list)
    )
    # tutor_score_weight가 0이면 이 회차는 튜터 평가를 아예 반영하지 않기로 한 것이므로,
    # 팀평가 쪽도 개인평가와 같은 기준으로 같이 끈다.
    tutor_team_sets_by_team = (
        _tutor_team_answer_sets(round_obj)
        if round_obj.tutor_score_weight > 0
        else defaultdict(list)
    )
    team_weight = Decimal(round_obj.team_score_weight) / 100
    personal_weight = Decimal(round_obj.personal_score_weight) / 100
    tutor_weight = Decimal(round_obj.tutor_score_weight) / 100
    team_submissions = defaultdict(list)
    peer_submissions = defaultdict(list)
    for submission in submissions:
        if submission.review_type == ReviewSubmission.ReviewType.TEAM:
            team_submissions[submission.target_team_id].append(submission)
        else:
            peer_submissions[submission.target_participant_id].append(submission)

    participant_count = round_obj.participants.count()
    teams = list(round_obj.teams.prefetch_related("memberships__participant"))
    team_rows = []
    team_score_by_id = {}
    for team in teams:
        expected = participant_count - team.memberships.count()
        received = team_submissions[team.pk]
        valid_sets = [values for values in _rating_sets(received) if values]
        # 튜터 팀평가는 점수 계산에는 섞이지만(팀 결과 심사 대상이 아니므로) 학생 제출
        # 현황(valid_count/expected_count/coverage)에는 포함하지 않는다 - 안 그러면
        # valid_count가 expected_count를 넘어 DB 체크 제약(valid_not_above_expected)에 걸린다.
        score = calculate_team_score(valid_sets + tutor_team_sets_by_team[team.pk])
        team_score_by_id[team.pk] = score
        team_rows.append(
            {
                "result_type": EvaluationResult.ResultType.TEAM,
                "team": team,
                "team_score_raw": score,
                "display_score": round_to_display(score) if score is not None else None,
                "primary_rank": None,
                "expected_count": expected,
                "valid_count": len(valid_sets),
                "coverage": calculate_coverage(expected, len(valid_sets)),
                "data_status": determine_data_status(expected, len(valid_sets)),
            }
        )
    _rank_rows(team_rows, "team_score_raw", "primary_rank")

    individual_rows = []
    for team in teams:
        team_score = team_score_by_id[team.pk]
        team_size = team.memberships.count()
        for membership in team.memberships.all():
            participant = membership.participant
            received = peer_submissions[participant.pk]
            valid_sets = [values for values in _rating_sets(received) if values]
            peer_score = calculate_peer_score(valid_sets)
            tutor_score = calculate_peer_score(tutor_sets_by_participant[participant.pk])
            final_score = calculate_final_score(
                team_score,
                peer_score,
                tutor_score,
                team_weight=team_weight,
                peer_weight=personal_weight,
                tutor_weight=tutor_weight,
            )
            expected = max(team_size - 1, 0)
            individual_rows.append(
                {
                    "result_type": EvaluationResult.ResultType.INDIVIDUAL,
                    "participant": participant,
                    "team_score_raw": team_score,
                    "peer_score_raw": peer_score,
                    "tutor_score_raw": tutor_score,
                    "final_score_raw": final_score,
                    "display_score": (
                        round_to_display(final_score) if final_score is not None else None
                    ),
                    "primary_rank": None,
                    "peer_rank": None,
                    "expected_count": expected,
                    "valid_count": len(valid_sets),
                    "coverage": calculate_coverage(expected, len(valid_sets)),
                    "data_status": determine_data_status(expected, len(valid_sets)),
                }
            )
    _rank_rows(individual_rows, "final_score_raw", "primary_rank")
    _rank_rows(individual_rows, "peer_score_raw", "peer_rank")
    digest_values = []
    for submission in submissions:
        values = _rating_sets([submission])[0]
        if values:
            digest_values.append((submission.pk, ",".join(str(value) for value in values)))
    return team_rows + individual_rows, compute_input_digest(digest_values)


def calculate_round(*, round_id, actor):
    with transaction.atomic():
        round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
        if round_obj.status != EvaluationRound.Status.COMPLETED:
            raise ValidationError("완료된 회차만 채점할 수 있습니다.")
        next_version = (
            round_obj.calculation_runs.aggregate(value=Max("version"))["value"] or 0
        ) + 1
        run = CalculationRun.objects.create(
            round=round_obj,
            version=next_version,
            formula_version=FORMULA_VERSION,
            executed_by=actor,
        )
    try:
        rows, digest = _build_result_rows(round_obj)
        with transaction.atomic():
            EvaluationResult.objects.bulk_create(
                [EvaluationResult(calculation_run=run, **row) for row in rows]
            )
            CalculationRun.objects.filter(round=round_obj, is_active=True).update(is_active=False)
            run.status = CalculationRun.Status.SUCCEEDED
            run.is_active = True
            run.input_digest = digest
            run.finished_at = timezone.now()
            run.save(update_fields=("status", "is_active", "input_digest", "finished_at"))
            record_event(
                action="CALCULATION_SUCCEEDED",
                target=run,
                actor=actor,
                round_obj=round_obj,
                summary={"version": run.version, "result_count": len(rows)},
            )
        return run
    except Exception as error:
        CalculationRun.objects.filter(pk=run.pk).update(
            status=CalculationRun.Status.FAILED,
            error_summary=type(error).__name__,
            finished_at=timezone.now(),
        )
        record_event(
            action="CALCULATION_FAILED",
            target=run,
            actor=actor,
            round_obj=round_obj,
            summary={"version": run.version, "error_type": type(error).__name__},
            succeeded=False,
        )
        raise


def _active_run_for_update(round_id):
    run = (
        CalculationRun.objects.select_for_update()
        .filter(round_id=round_id, is_active=True, status=CalculationRun.Status.SUCCEEDED)
        .first()
    )
    if not run:
        raise ValidationError("먼저 채점을 실행해 주세요.")
    return run


def _guard_partial_publication(run, *, turning_on, partial_confirmed):
    if not turning_on or partial_confirmed:
        return
    if run.results.filter(data_status=EvaluationResult.DataStatus.PARTIAL).exists():
        # 화면에서 이 code를 보고 에러 메시지 대신 "그래도 공개할까요?" 확인 배너를 띄운다.
        raise ValidationError(
            "일부 제출 결과 공개에는 추가 확인이 필요합니다.",
            code=PARTIAL_CONFIRMATION_REQUIRED,
        )


@transaction.atomic
def _announce_results_published(run):
    """학생이 실제로 자기 점수를 볼 수 있게 되는 순간에만 알린다.

    공개 항목은 넷이지만 학생 화면에 점수가 뜨는 기준은 my_score다. 항목을 켤 때마다
    알리면 같은 회차로 알림이 네 번 간다.
    """
    from accounts.email_services import send_results_released_email

    round_obj = run.round
    announce(
        [participant.user for participant in round_obj.participants.select_related("user")],
        category=Notification.Category.RESULTS_PUBLISHED,
        title="평가 결과가 공개되었습니다",
        message=f"'{round_obj.title}' 회차의 내 점수를 확인할 수 있습니다.",
        link=reverse("accounts:mypage"),
        email_sender=lambda users: send_results_released_email(
            round_obj, [user.email for user in users]
        ),
    )


def toggle_publication(*, round_id, item_key, actor, partial_confirmed=False):
    field = PUBLICATION_FIELDS.get(item_key)
    if not field:
        raise ValidationError("알 수 없는 공개 항목입니다.")
    run = _active_run_for_update(round_id)
    turning_on = getattr(run, field) is None
    _guard_partial_publication(run, turning_on=turning_on, partial_confirmed=partial_confirmed)
    setattr(run, field, timezone.now() if turning_on else None)
    run.save(update_fields=(field,))
    record_event(
        action="PUBLICATION_CHANGED",
        target=run,
        actor=actor,
        round_obj=run.round,
        summary={"item": item_key, "published": turning_on, "partial_confirmed": partial_confirmed},
    )
    if turning_on and item_key == "my_score":
        _announce_results_published(run)
    return run


@transaction.atomic
def toggle_all_publications(*, round_id, actor, partial_confirmed=False):
    """4개 공개 항목을 한 번에 켜고 끈다.

    하나라도 비공개면 전체 공개, 이미 전부 공개면 전체 비공개다. 일부 제출 데이터가 있을 때
    추가 확인을 요구하는 규칙은 개별 토글과 같다 (RES-011).
    """
    run = _active_run_for_update(round_id)
    fields = tuple(PUBLICATION_FIELDS.values())
    turning_on = any(getattr(run, field) is None for field in fields)
    _guard_partial_publication(run, turning_on=turning_on, partial_confirmed=partial_confirmed)
    published_at = timezone.now() if turning_on else None
    for field in fields:
        setattr(run, field, published_at)
    run.save(update_fields=fields)
    record_event(
        action="PUBLICATION_CHANGED",
        target=run,
        actor=actor,
        round_obj=run.round,
        summary={"item": "ALL", "published": turning_on, "partial_confirmed": partial_confirmed},
    )
    if turning_on:
        _announce_results_published(run)
    return run


@transaction.atomic
def add_tutor_note(*, student_id, body, actor):
    """수강생 한 명에 대한 튜터 전용 메모를 기록에 새로 추가한다.

    회차와 무관하게 학생당 여러 건이 쌓이며, 기존 메모는 건드리지 않는다 - 언제 무슨
    맥락으로 남겼는지가 중요해서 덮어쓰지 않는다. 감사 로그에는 메모 원문을 남기지
    않는다 (audit.services.record_event 규칙).
    """
    student = User.objects.filter(pk=student_id, role=User.Role.STUDENT).first()
    if not student:
        raise ValidationError("수강생 계정이 아닙니다.")
    body = (body or "").strip()
    if not body:
        raise ValidationError("메모 내용을 입력해 주세요.")
    if len(body) > TUTOR_NOTE_MAX_LENGTH:
        raise ValidationError(f"메모는 {TUTOR_NOTE_MAX_LENGTH}자까지 저장할 수 있습니다.")
    note = TutorNote.objects.create(student=student, body=body, author=actor)
    record_event(
        action="TUTOR_NOTE_ADDED",
        target=student,
        actor=actor,
        summary={"student_id": student.pk, "length": len(body)},
    )
    return note


@transaction.atomic
def delete_tutor_note(*, student_id, note_id, actor):
    """메모 기록 한 건을 지운다. 학생 ID까지 맞아야 지운다 - URL의 note_id만으로
    다른 학생의 메모를 잘못 지우는 사고를 막는다."""
    note = (
        TutorNote.objects.filter(pk=note_id, student_id=student_id)
        .select_related("student")
        .first()
    )
    if not note:
        raise ValidationError("이미 지워졌거나 존재하지 않는 메모입니다.")
    student = note.student
    note.delete()
    record_event(
        action="TUTOR_NOTE_DELETED",
        target=student,
        actor=actor,
        summary={"student_id": student_id, "note_id": note_id},
    )


@transaction.atomic
def delete_all_tutor_notes(*, student_id, actor):
    """수강생 한 명의 메모 기록을 전부 지운다."""
    student = User.objects.filter(pk=student_id, role=User.Role.STUDENT).first()
    if not student:
        raise ValidationError("수강생 계정이 아닙니다.")
    deleted_count, _ = TutorNote.objects.filter(student=student).delete()
    if not deleted_count:
        return
    record_event(
        action="TUTOR_NOTE_ALL_DELETED",
        target=student,
        actor=actor,
        summary={"student_id": student.pk, "count": deleted_count},
    )


def tutor_notes_by_student():
    """수강생 관리 화면용 - 학생 계정 ID -> 메모 기록(최신순).

    화면에 뿌릴 만큼 가벼운 목록이라(학생 한 명당 많아야 수십 건) 학생별로 쪼개 조회하지
    않고 한 번에 불러와 그룹만 짓는다.
    """
    notes_by_student = defaultdict(list)
    notes = TutorNote.objects.select_related("author").filter(student__role=User.Role.STUDENT)
    for note in notes:
        notes_by_student[note.student_id].append(note)
    return dict(notes_by_student)


def previous_final_scores(round_obj):
    """직전 회차(이 회차보다 먼저 완료됐고 활성 채점이 있는 가장 최근 회차)의 학생별 최종점수.

    추이 배지("지난 회차 대비 상승/하락")를 그리는 데 쓴다. 회차마다 참가자 행이 새로 생기므로
    회차를 가로지르는 식별자인 사용자 ID를 키로 돌려준다.
    """
    if not round_obj.completed_at:
        return {}
    previous_round = (
        EvaluationRound.objects.filter(
            status=EvaluationRound.Status.COMPLETED,
            completed_at__lt=round_obj.completed_at,
            calculation_runs__is_active=True,
        )
        .order_by("-completed_at")
        .first()
    )
    if not previous_round:
        return {}
    rows = EvaluationResult.objects.filter(
        calculation_run__round=previous_round,
        calculation_run__is_active=True,
        result_type=EvaluationResult.ResultType.INDIVIDUAL,
        final_score_raw__isnull=False,
    ).values_list("participant__user_id", "final_score_raw")
    return dict(rows)
