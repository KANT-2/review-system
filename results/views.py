from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.permissions import is_operations_user, is_student_user
from results.application import (
    PARTIAL_CONFIRMATION_REQUIRED,
    PUBLICATION_FIELDS,
    calculate_round,
    previous_final_scores,
    save_tutor_note,
    toggle_all_publications,
    toggle_publication,
)
from results.models import CalculationRun, EvaluationResult, TutorNote
from results.services import PEER_WEIGHT, TEAM_WEIGHT, reveal_if_published, round_to_display
from rounds.models import EvaluationRound, RoundParticipant

# 상위 몇 개까지 펼친 채로 접을지 (팀 순위 / 개인 결과 공통).
VISIBLE_ROW_COUNT = 3
# 마스터 스위치(전체 공개)를 개별 항목과 구분하기 위한 확인 배너 키.
PUBLISH_ALL_KEY = "ALL"

PUBLISH_ITEMS = [
    {"key": "team_winner", "label": "팀 1위", "hint": "이번 회차 1위 팀 이름을 전체 학생에게 공개"},
    {
        "key": "team_ranking",
        "label": "전체 팀 순위",
        "hint": "모든 팀의 순위와 점수를 학생에게 공개",
    },
    {
        "key": "my_score",
        "label": "내 최종 점수",
        "hint": "학생 본인의 최종점수를 본인에게만 공개",
    },
    {
        "key": "peer_ranking",
        "label": "내 개인 순위",
        "hint": "전체 학생 중 본인 순위를 본인에게만 공개",
    },
]
PUBLISH_LABELS = {item["key"]: item["label"] for item in PUBLISH_ITEMS}
PUBLISH_KEYS = set(PUBLISH_LABELS)


@login_required
def manage_results(request, round_id):
    if not is_operations_user(request.user):
        raise PermissionDenied
    round_obj = EvaluationRound.objects.filter(pk=round_id).first()
    if not round_obj:
        raise PermissionDenied
    run = CalculationRun.objects.filter(round=round_obj, is_active=True).first()
    team_results = []
    individual_results = []
    if run:
        # 순위가 없는 행(N/A)은 어느 DB에서든 항상 맨 뒤로 - SQLite와 PostgreSQL은
        # NULL 정렬 기본값이 서로 반대다.
        team_results = _mark_ties(
            list(
                run.results.filter(result_type=EvaluationResult.ResultType.TEAM)
                .select_related("team")
                .prefetch_related("team__memberships__participant")
                .order_by(F("primary_rank").asc(nulls_last=True), "team__team_number")
            )
        )
        individual_results = _mark_ties(
            list(
                run.results.filter(result_type=EvaluationResult.ResultType.INDIVIDUAL)
                .select_related("participant", "participant__team_membership__team")
                .order_by(
                    F("primary_rank").asc(nulls_last=True),
                    "participant__display_name_snapshot",
                )
            )
        )
        _attach_trend(individual_results, previous_final_scores(round_obj))
    publication_rows = [
        {
            **item,
            "published": bool(run and getattr(run, PUBLICATION_FIELDS[item["key"]])),
            "published_at": getattr(run, PUBLICATION_FIELDS[item["key"]]) if run else None,
        }
        for item in PUBLISH_ITEMS
    ]
    pending_confirm = request.GET.get("confirm")
    if pending_confirm not in PUBLISH_KEYS | {PUBLISH_ALL_KEY}:
        pending_confirm = None
    return render(
        request,
        "results/round_manage.html",
        {
            "round_obj": round_obj,
            "round_options": EvaluationRound.objects.order_by("-created_at").only("id", "title"),
            "run": run,
            "all_published": bool(run) and all(row["published"] for row in publication_rows),
            "notes": _notes_by_participant(individual_results),
            "team_results": team_results,
            "individual_results": individual_results,
            "team_head": team_results[:VISIBLE_ROW_COUNT],
            "team_rest": team_results[VISIBLE_ROW_COUNT:],
            "individual_head": individual_results[:VISIBLE_ROW_COUNT],
            "individual_rest": individual_results[VISIBLE_ROW_COUNT:],
            "summary": _build_summary(round_obj, team_results, individual_results),
            "publish_items": publication_rows,
            "pending_confirm": pending_confirm,
            "team_weight_percent": int(TEAM_WEIGHT * 100),
            "peer_weight_percent": int(PEER_WEIGHT * 100),
            "has_partial": any(
                result.data_status == EvaluationResult.DataStatus.PARTIAL
                for result in team_results + individual_results
            ),
        },
    )


def _mark_ties(results):
    """같은 순위를 나눠 가진 행에 ``is_tied``를 달아 화면에서 '공동'으로 표시하게 한다."""
    counts = Counter(result.primary_rank for result in results if result.primary_rank)
    for result in results:
        result.is_tied = counts.get(result.primary_rank, 0) > 1
    return results


def _attach_trend(results, previous_scores):
    """지난 회차 대비 최종점수 추이(상승/하락/변화없음)를 각 행에 달아 준다.

    두 회차 모두 최종점수가 있는 학생만 대상이다 - 한쪽이 N/A면 비교 자체가 성립하지 않는다.
    차이는 표시 정밀도(소수 둘째 자리)로 계산한다.
    """
    for result in results:
        result.trend_direction = None
        result.trend_delta = None
        previous = previous_scores.get(result.participant.user_id)
        if previous is None or result.final_score_raw is None:
            continue
        delta = round_to_display(result.final_score_raw) - round_to_display(previous)
        if delta > 0:
            result.trend_direction, result.trend_delta = "up", delta
        elif delta < 0:
            result.trend_direction, result.trend_delta = "down", -delta
        else:
            result.trend_direction = "flat"
    return results


def _notes_by_participant(individual_results):
    """참가자 ID -> 튜터 메모 본문. 운영자 화면에서만 조회한다."""
    participant_ids = [result.participant_id for result in individual_results]
    return dict(
        TutorNote.objects.filter(participant_id__in=participant_ids).values_list(
            "participant_id", "body"
        )
    )


def _build_summary(round_obj, team_results, individual_results):
    """결과 화면 상단 요약 카드 3장에 쓰는 값."""
    return {
        "participant_count": round_obj.participants.count(),
        "team_count": round_obj.teams.count(),
        "na_count": sum(1 for result in individual_results if result.final_score_raw is None),
        "top_team": next(
            (result for result in team_results if result.primary_rank == 1),
            None,
        ),
        "top_student": next(
            (result for result in individual_results if result.primary_rank == 1),
            None,
        ),
    }


@login_required
@require_POST
def calculate(request, round_id):
    if not is_operations_user(request.user):
        raise PermissionDenied
    try:
        run = calculate_round(round_id=round_id, actor=request.user)
    except (EvaluationRound.DoesNotExist, ValidationError) as error:
        messages.error(request, " ".join(getattr(error, "messages", [str(error)])))
    else:
        messages.success(
            request, f"채점 v{run.version}을 완료했습니다. 공개 항목은 초기화됐습니다."
        )
    return redirect("rounds:results", round_id=round_id)


@login_required
@require_POST
def publish(request, round_id, item_key):
    if not is_operations_user(request.user):
        raise PermissionDenied
    results_url = reverse("rounds:results", kwargs={"round_id": round_id})
    try:
        run = toggle_publication(
            round_id=round_id,
            item_key=item_key,
            actor=request.user,
            partial_confirmed=request.POST.get("partial_confirmed") == "1",
        )
    except ValidationError as error:
        if getattr(error, "code", None) == PARTIAL_CONFIRMATION_REQUIRED:
            # 에러가 아니라 한 번 더 묻는 단계다 - 화면에 확인 배너를 띄운다.
            return redirect(f"{results_url}?confirm={item_key}#publish")
        messages.error(request, " ".join(error.messages))
    else:
        is_published = getattr(run, PUBLICATION_FIELDS[item_key]) is not None
        messages.success(
            request,
            f"'{PUBLISH_LABELS[item_key]}' 항목을 {'공개' if is_published else '비공개'}로 "
            "전환했습니다.",
        )
    return redirect(f"{results_url}#publish")


@login_required
@require_POST
def publish_all(request, round_id):
    """마스터 스위치: 4개 공개 항목을 한 번에 켜고 끈다."""
    if not is_operations_user(request.user):
        raise PermissionDenied
    results_url = reverse("rounds:results", kwargs={"round_id": round_id})
    try:
        run = toggle_all_publications(
            round_id=round_id,
            actor=request.user,
            partial_confirmed=request.POST.get("partial_confirmed") == "1",
        )
    except ValidationError as error:
        if getattr(error, "code", None) == PARTIAL_CONFIRMATION_REQUIRED:
            return redirect(f"{results_url}?confirm={PUBLISH_ALL_KEY}#publish")
        messages.error(request, " ".join(error.messages))
    else:
        is_published = getattr(run, PUBLICATION_FIELDS["team_winner"]) is not None
        messages.success(
            request, f"전체 결과를 {'공개' if is_published else '비공개'}로 전환했습니다."
        )
    return redirect(f"{results_url}#publish")


@login_required
@require_POST
def save_note(request, round_id, participant_id):
    """수강생별 튜터 전용 메모 저장. 학생 화면에는 노출되지 않는다."""
    if not is_operations_user(request.user):
        raise PermissionDenied
    try:
        save_tutor_note(
            round_id=round_id,
            participant_id=participant_id,
            body=request.POST.get("body", ""),
            actor=request.user,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "메모를 저장했습니다.")
    return redirect(reverse("rounds:results", kwargs={"round_id": round_id}))


@login_required
def my_results(request):
    if not is_student_user(request.user):
        raise PermissionDenied
    # 채점이 끝난 회차는 모두 열어 둔다 - 최신 회차만 보이면 지난 결과를 다시 볼 수 없다.
    available = list(
        RoundParticipant.objects.filter(
            user=request.user,
            round__status=EvaluationRound.Status.COMPLETED,
            round__calculation_runs__is_active=True,
        )
        .select_related("round", "team_membership__team")
        .order_by("-round__completed_at")
    )
    if not available:
        return render(
            request, "results/student_me.html", {"participant": None, "available_rounds": []}
        )
    requested = request.GET.get("round")
    participant = None
    if requested and requested.isdigit():
        participant = next((row for row in available if row.round_id == int(requested)), None)
    if participant is None:
        participant = available[0]
    run = CalculationRun.objects.get(round=participant.round, is_active=True)
    my_result = run.results.filter(
        result_type=EvaluationResult.ResultType.INDIVIDUAL, participant=participant
    ).first()
    team_results = (
        _mark_ties(
            list(
                run.results.filter(result_type=EvaluationResult.ResultType.TEAM)
                .select_related("team")
                .order_by(F("primary_rank").asc(nulls_last=True), "team__team_number")
            )
        )
        if run.team_ranking_published_at
        else []
    )
    winner = (
        run.results.filter(result_type=EvaluationResult.ResultType.TEAM, primary_rank=1)
        .select_related("team")
        .first()
        if run.winner_published_at
        else None
    )
    my_team = getattr(participant, "team_membership", None)
    return render(
        request,
        "results/student_me.html",
        {
            "participant": participant,
            "available_rounds": available,
            "selected_round_id": participant.round_id,
            "run": run,
            # 항목별 공개 게이트(RES-010) - 공개 시각이 없으면 값 자체를 넘기지 않는다.
            "my_result": reveal_if_published(my_result, run.my_score_published_at),
            "my_rank": (
                reveal_if_published(my_result.peer_rank, run.peer_ranking_published_at)
                if my_result
                else None
            ),
            "winner": winner,
            "team_results": team_results,
            "team_head": team_results[:VISIBLE_ROW_COUNT],
            "team_rest": team_results[VISIBLE_ROW_COUNT:],
            "my_team_id": my_team.team_id if my_team else None,
            # 공개했는데 값이 N/A인 경우를 "비공개"와 구분해 안내하기 위해 공개 여부도 넘긴다.
            "published": {
                key: getattr(run, field) is not None for key, field in PUBLICATION_FIELDS.items()
            },
            "team_weight_percent": int(TEAM_WEIGHT * 100),
            "peer_weight_percent": int(PEER_WEIGHT * 100),
        },
    )
