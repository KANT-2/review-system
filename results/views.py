from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from results.fake_data import PUBLISHED_AT, build_scenario
from results.services import reveal_if_published

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

# 프로토타입 회차 선택기 - rounds 앱에 실제 모델이 없어서 회차 목록도 하드코딩한다.
# "3"(현재 회차)만 실제 시나리오 데이터가 있고, 나머지는 준비중 상태를 보여준다.
LATEST_ROUND = "3"
ROUND_OPTIONS = [("1", "1회차"), ("2", "2회차"), ("3", "3회차 (현재)")]
ROUND_LABELS = dict(ROUND_OPTIONS)


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
    selected_round = request.GET.get("round", LATEST_ROUND)
    if selected_round not in ROUND_LABELS:
        selected_round = LATEST_ROUND
    is_latest_round = selected_round == LATEST_ROUND
    base_context = {
        "active_nav": "manage",
        "round_options": ROUND_OPTIONS,
        "selected_round": selected_round,
        "round_label": ROUND_LABELS[selected_round],
        "is_latest_round": is_latest_round,
    }

    if not is_latest_round:
        return render(request, "results/manage.html", base_context)

    scenario = build_scenario()
    publish_state = _get_publish_state(request)
    has_partial_data = any(team.data_status == "PARTIAL" for team in scenario["teams"]) or any(
        student.peer_data_status == "PARTIAL" for student in scenario["students"]
    )
    return render(
        request,
        "results/manage.html",
        {
            **base_context,
            "scenario": scenario,
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
