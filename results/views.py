from django.shortcuts import render

from results.fake_data import build_scenario, reveal


def manage_preview(request):
    """PG-25 '결과·공개' 화면 프로토타입 (튜터/관리자용).

    가짜 데이터를 results/services.py의 실제 계산 함수에 통과시켜 만든 화면이다. accounts와
    rounds 모델이 아직 없어서 실제 권한 검사·회차 조회는 하지 않는다 - 나중에 그 모델들이
    생기면 이 뷰는 실제 CalculationRun/EvaluationResult 조회로 바뀐다.
    """
    scenario = build_scenario()
    return render(
        request,
        "results/manage.html",
        {
            "scenario": scenario,
        },
    )


def me_preview(request):
    """PG-16 '내 결과' 화면 프로토타입 (수강생용, 학생A 시점).

    항목별 독립 공개(RES-010)를 실제로 시연한다 - 본인 개인 순위는 아직 비공개 상태로 보여준다.
    """
    scenario = build_scenario()
    me = next(s for s in scenario["students"] if s.name == "학생A")
    published_at = scenario["published_at"]
    winner_team = scenario["winner_team"]

    context = {
        "round_name": scenario["round_name"],
        "me": me,
        "team_winner_number": reveal(winner_team.number if winner_team else None, "team_winner"),
        "team_ranking": reveal(scenario["teams_by_rank"], "team_ranking"),
        "my_score": reveal(me, "my_score"),
        "my_rank": reveal(me.rank, "peer_ranking"),
        "published_at": published_at,
    }
    return render(request, "results/me.html", context)
