from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from audit.services import record_event
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
from reviews.models import ReviewSubmission
from rounds.models import EvaluationRound, RoundParticipant

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


def _build_result_rows(round_obj):
    submissions = list(ReviewSubmission.objects.filter(round=round_obj).prefetch_related("answers"))
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
        score = calculate_team_score(valid_sets)
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
            final_score = calculate_final_score(team_score, peer_score)
            expected = max(team_size - 1, 0)
            individual_rows.append(
                {
                    "result_type": EvaluationResult.ResultType.INDIVIDUAL,
                    "participant": participant,
                    "team_score_raw": team_score,
                    "peer_score_raw": peer_score,
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
    return run


@transaction.atomic
def save_tutor_note(*, round_id, participant_id, body, actor):
    """수강생 한 명에 대한 튜터 전용 메모를 저장한다. 빈 내용으로 저장하면 메모를 지운다.

    감사 로그에는 메모 원문을 남기지 않는다 (audit.services.record_event 규칙).
    """
    participant = RoundParticipant.objects.filter(pk=participant_id, round_id=round_id).first()
    if not participant:
        raise ValidationError("이 회차의 수강생이 아닙니다.")
    body = (body or "").strip()
    if len(body) > TUTOR_NOTE_MAX_LENGTH:
        raise ValidationError(f"메모는 {TUTOR_NOTE_MAX_LENGTH}자까지 저장할 수 있습니다.")
    if body:
        note, _ = TutorNote.objects.update_or_create(
            participant=participant, defaults={"body": body, "author": actor}
        )
        cleared = False
    else:
        note = TutorNote.objects.filter(participant=participant).first()
        if not note:
            return None
        TutorNote.objects.filter(pk=note.pk).delete()
        cleared = True
    record_event(
        action="TUTOR_NOTE_CHANGED",
        target=participant,
        actor=actor,
        round_obj=participant.round,
        summary={"participant_id": participant.pk, "cleared": cleared, "length": len(body)},
    )
    return None if cleared else note


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
