from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.permissions import is_operations_user, is_student_user
from results.application import PUBLICATION_FIELDS, calculate_round, toggle_publication
from results.fake_data import PUBLISHED_AT, build_scenario
from results.models import CalculationRun, EvaluationResult
from results.services import reveal_if_published
from rounds.models import EvaluationRound, RoundParticipant

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
    run = (
        CalculationRun.objects.filter(round=round_obj, is_active=True)
        .prefetch_related(
            "results__team__memberships__participant",
            "results__participant__team_membership__team",
        )
        .first()
    )
    team_results = []
    individual_results = []
    if run:
        team_results = run.results.filter(result_type=EvaluationResult.ResultType.TEAM).order_by(
            "primary_rank", "team__team_number"
        )
        individual_results = run.results.filter(
            result_type=EvaluationResult.ResultType.INDIVIDUAL
        ).order_by("primary_rank", "participant__display_name_snapshot")
    publication_rows = [
        {
            **item,
            "published": bool(run and getattr(run, PUBLICATION_FIELDS[item["key"]])),
        }
        for item in PUBLISH_ITEMS
    ]
    return render(
        request,
        "results/round_manage.html",
        {
            "round_obj": round_obj,
            "run": run,
            "team_results": team_results,
            "individual_results": individual_results,
            "publish_items": publication_rows,
            "has_partial": bool(
                run and run.results.filter(data_status=EvaluationResult.DataStatus.PARTIAL).exists()
            ),
        },
    )


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
    try:
        toggle_publication(
            round_id=round_id,
            item_key=item_key,
            actor=request.user,
            partial_confirmed=request.POST.get("partial_confirmed") == "1",
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "결과 공개 설정을 변경했습니다.")
    return redirect("rounds:results", round_id=round_id)


@login_required
def my_results(request):
    if not is_student_user(request.user):
        raise PermissionDenied
    participant = (
        RoundParticipant.objects.filter(
            user=request.user,
            round__status=EvaluationRound.Status.COMPLETED,
            round__calculation_runs__is_active=True,
        )
        .select_related("round", "team_membership__team")
        .order_by("-round__completed_at")
        .first()
    )
    if not participant:
        return render(request, "results/student_me.html", {"participant": None})
    run = CalculationRun.objects.get(round=participant.round, is_active=True)
    my_result = run.results.filter(
        result_type=EvaluationResult.ResultType.INDIVIDUAL, participant=participant
    ).first()
    team_results = (
        run.results.filter(result_type=EvaluationResult.ResultType.TEAM).order_by(
            "primary_rank", "team__team_number"
        )
        if run.team_ranking_published_at
        else []
    )
    winner = (
        run.results.filter(result_type=EvaluationResult.ResultType.TEAM, primary_rank=1).first()
        if run.winner_published_at
        else None
    )
    return render(
        request,
        "results/student_me.html",
        {
            "participant": participant,
            "run": run,
            "my_result": my_result if run.my_score_published_at else None,
            "my_rank": my_result.peer_rank if my_result and run.peer_ranking_published_at else None,
            "winner": winner,
            "team_results": team_results,
        },
    )


def _get_publish_state(request):
    """세션에 저장된 항목별 공개 상태(bool). 저장된 모델이 없어서 세션으로 대신하는
    프로토타입 전용 장치 - 실제 구현에서는 CalculationRun의 *_published_at 컬럼이 된다."""
    if "publish_state" not in request.session:
        request.session["publish_state"] = {
            key: value is not None for key, value in PUBLISHED_AT.items()
        }
    return request.session["publish_state"]


def _reveal(request, value, key):
    is_published = _get_publish_state(request).get(key, False)
    return reveal_if_published(value, True if is_published else None)


def manage_preview(request):
    """PG-25 '결과·공개' 화면 프로토타입 (튜터/관리자용).

    가짜 데이터를 results/services.py의 실제 계산 함수에 통과시켜 만든 화면이다. accounts와
    rounds 모델이 아직 없어서 실제 권한 검사·회차 조회는 하지 않는다 - 나중에 그 모델들이
    생기면 이 뷰는 실제 CalculationRun/EvaluationResult 조회로 바뀐다.
    """
    scenario = build_scenario()
    publish_state = _get_publish_state(request)
    has_partial_data = any(team.data_status == "PARTIAL" for team in scenario["teams"]) or any(
        student.peer_data_status == "PARTIAL" for student in scenario["students"]
    )
    return render(
        request,
        "results/manage.html",
        {
            "scenario": scenario,
            "active_nav": "manage",
            "publish_items": PUBLISH_ITEMS,
            "publish_state": publish_state,
            "pending_confirm": request.session.get("pending_confirm"),
            "has_partial_data": has_partial_data,
        },
    )


@require_POST
def toggle_publish(request, item_key):
    """RES-010/011 프로토타입: 항목별 공개를 켜고 끈다.

    켜려는 항목이 있고(off->on) 이번 회차에 PARTIAL 데이터가 있으면, 바로 공개하지 않고
    한 번 더 확인을 요구한다(세션에 pending_confirm만 표시하고 실제 상태는 안 바꿈).
    이미 확인을 거쳤으면(POST에 confirm=1) 그대로 진행한다. 끄는 것(on->off)은 확인 없이
    바로 처리한다.
    """
    if item_key not in PUBLISH_KEYS:
        return redirect("results:manage_preview")

    publish_state = _get_publish_state(request)
    turning_on = not publish_state.get(item_key, False)
    confirmed = request.POST.get("confirm") == "1"

    scenario = build_scenario()
    has_partial_data = any(team.data_status == "PARTIAL" for team in scenario["teams"]) or any(
        student.peer_data_status == "PARTIAL" for student in scenario["students"]
    )

    if turning_on and has_partial_data and not confirmed:
        request.session["pending_confirm"] = item_key
    else:
        publish_state[item_key] = turning_on
        request.session["publish_state"] = publish_state
        request.session.pop("pending_confirm", None)
        label = PUBLISH_LABELS[item_key]
        messages.success(
            request, f"'{label}' 항목을 {'공개' if turning_on else '비공개'}로 전환했습니다."
        )

    request.session.modified = True
    return redirect(reverse("results:manage_preview") + "#publish")


@require_POST
def cancel_publish_confirm(request):
    request.session.pop("pending_confirm", None)
    request.session.modified = True
    return redirect(reverse("results:manage_preview") + "#publish")


def me_preview(request):
    """PG-16 '내 결과' 화면 프로토타입 (수강생용, 학생A 시점).

    항목별 독립 공개(RES-010)를 실제로 시연한다 - 관리 화면에서 토글한 상태가 그대로
    반영된다(같은 세션 기준).
    """
    scenario = build_scenario()
    me = next(s for s in scenario["students"] if s.name == "학생A")
    winner_team = scenario["winner_team"]

    context = {
        "round_name": scenario["round_name"],
        "me": me,
        "team_winner_number": _reveal(
            request, winner_team.number if winner_team else None, "team_winner"
        ),
        "team_ranking": _reveal(request, scenario["teams_by_rank"], "team_ranking"),
        "my_score": _reveal(request, me, "my_score"),
        "my_rank": _reveal(request, me.rank, "peer_ranking"),
        "publish_state": _get_publish_state(request),
        "active_nav": "me",
    }
    return render(request, "results/me.html", context)
