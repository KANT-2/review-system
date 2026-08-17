from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from audit.services import record_event
from results.models import CalculationRun, EvaluationResult
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
from rounds.models import EvaluationRound

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


@transaction.atomic
def toggle_publication(*, round_id, item_key, actor, partial_confirmed=False):
    field = PUBLICATION_FIELDS.get(item_key)
    if not field:
        raise ValidationError("알 수 없는 공개 항목입니다.")
    run = (
        CalculationRun.objects.select_for_update()
        .filter(round_id=round_id, is_active=True, status=CalculationRun.Status.SUCCEEDED)
        .first()
    )
    if not run:
        raise ValidationError("먼저 채점을 실행해 주세요.")
    turning_on = getattr(run, field) is None
    has_partial = run.results.filter(data_status=EvaluationResult.DataStatus.PARTIAL).exists()
    if turning_on and has_partial and not partial_confirmed:
        raise ValidationError("일부 제출 결과 공개에는 추가 확인이 필요합니다.")
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
