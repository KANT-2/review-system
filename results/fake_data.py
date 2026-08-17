"""Builds one representative scenario for the results screen prototype.

This is prototype-only scaffolding (no models exist yet for accounts/rounds/teams). It feeds
made-up raw evaluation answers through the REAL functions in results/services.py, so every
number the templates show (scores, ranks, N/A, coverage, seed) is actually computed by the
production logic, not hand-typed. Once accounts/rounds/teams have real models, this module goes
away and views will pull the same shape of data from the database instead.
"""

from dataclasses import dataclass
from decimal import Decimal

from results.services import (
    calculate_coverage,
    calculate_final_score,
    calculate_peer_score,
    calculate_seed,
    calculate_team_score,
    competition_rank,
    determine_data_status,
    reveal_if_published,
    round_to_display,
)


@dataclass
class TeamRow:
    number: int
    member_names: list[str]
    expected_reviews: int
    valid_reviews: int
    team_score: Decimal | None
    data_status: str
    coverage: Decimal | None
    rank: int | None = None
    is_tied: bool = False


@dataclass
class StudentRow:
    name: str
    team_number: int
    expected_peer_reviews: int
    valid_peer_reviews: int
    peer_data_status: str
    peer_coverage: Decimal | None
    team_score: Decimal | None
    peer_score: Decimal | None
    tutor_score: Decimal | None
    final_score: Decimal | None
    rank: int | None = None
    is_tied: bool = False


# 4개 항목 독립 공개 데모용: 팀1위/전체팀순위/본인최종점수는 공개, 본인개인순위는 아직 비공개.
PUBLISHED_AT = {
    "team_winner": "2026-08-15T09:00:00Z",
    "team_ranking": "2026-08-15T09:00:00Z",
    "my_score": "2026-08-15T09:00:00Z",
    "peer_ranking": None,
}


def build_scenario():
    # ---- 팀 평가: 팀마다 기대 3건(다른 팀 수 - 1) ----
    team_reviews_received = {
        1: [[5, 5, 4, 5, 5], [5, 4, 5, 5, 4], [4, 5, 5, 4, 5]],  # 3/3 COMPLETE
        2: [[4, 3, 4, 3, 4], [3, 4, 3, 4, 3]],  # 2/3 PARTIAL
        3: [],  # 0/3 NO_DATA
        4: [[4, 4, 4, 4, 4], [4, 3, 4, 4, 3], [3, 4, 4, 3, 4]],  # 3/3 COMPLETE
    }
    expected_team_reviews = 3

    teams = {}
    for number, received in team_reviews_received.items():
        team_score = calculate_team_score(received)
        valid = len(received)
        teams[number] = TeamRow(
            number=number,
            member_names=[],
            expected_reviews=expected_team_reviews,
            valid_reviews=valid,
            team_score=team_score,
            data_status=determine_data_status(expected_team_reviews, valid),
            coverage=calculate_coverage(expected_team_reviews, valid),
            rank=None,
        )

    # ---- 학생·개인 평가 ----
    # (이름, 소속 팀, 기대 개인평가 수, 받은 답변 목록, 튜터 평가 점수)
    # 튜터 평가는 도입이 확정된 기능이라 모든 학생의 최종점수 계산에 항상 반영한다
    # (팀 30% + 개인 40% + 튜터 30%, results/services.py TEAM_WEIGHT_WITH_TUTOR 등 참고).
    # 튜터가 실제로 점수를 매기는 입력 화면은 아직 안 만들었으므로 여기서는 가짜 튜터 점수를
    # 대입한다 - 구성 점수(팀/개인) 중 하나라도 N/A인 학생은 튜터 점수가 있어도 최종점수가
    # N/A인 건 동일하다(calculate_final_score의 기존 규칙).
    student_specs = [
        ("학생A", 1, 2, [[5, 5, 5, 4, 5], [5, 4, 5, 5, 5]], Decimal("88.00")),
        ("학생B", 1, 2, [[5, 5, 4, 5, 5], [4, 5, 5, 5, 4]], Decimal("90.00")),
        ("학생C", 1, 2, [[3, 4, 3, 3, 4]], Decimal("76.00")),
        ("학생D", 2, 2, [], Decimal("70.00")),
        ("학생E", 2, 2, [[4, 4, 3, 4, 4], [4, 4, 4, 3, 4]], Decimal("82.00")),
        ("학생F", 2, 2, [[3, 3, 4, 3, 3], [4, 3, 3, 4, 3]], Decimal("74.00")),
        ("학생G", 3, 1, [[4, 4, 4, 4, 4]], Decimal("78.00")),
        ("학생H", 3, 1, [], Decimal("65.00")),
        ("학생I", 4, 0, [], Decimal("85.00")),
    ]

    students = []
    for name, team_number, expected_peer, received, tutor_score in student_specs:
        team_score = teams[team_number].team_score
        peer_score = calculate_peer_score(received)
        final_score = calculate_final_score(team_score, peer_score, tutor_score)
        valid_peer = len(received)
        students.append(
            StudentRow(
                name=name,
                team_number=team_number,
                expected_peer_reviews=expected_peer,
                valid_peer_reviews=valid_peer,
                peer_data_status=determine_data_status(expected_peer, valid_peer),
                peer_coverage=calculate_coverage(expected_peer, valid_peer),
                team_score=team_score,
                peer_score=peer_score,
                tutor_score=tutor_score,
                final_score=final_score,
                rank=None,
            )
        )
        teams[team_number].member_names.append(name)

    # ---- 순위: N/A 제외, 공개 점수(표시 정밀도) 기준 경쟁 순위 ----
    ranked_teams = sorted(
        (t for t in teams.values() if t.team_score is not None),
        key=lambda t: t.team_score,
        reverse=True,
    )
    team_display_scores = [round_to_display(t.team_score) for t in ranked_teams]
    team_ranks = competition_rank(team_display_scores)
    for team, rank in zip(ranked_teams, team_ranks, strict=True):
        team.rank = rank
        team.is_tied = team_ranks.count(rank) > 1

    ranked_students = sorted(
        (s for s in students if s.final_score is not None),
        key=lambda s: s.final_score,
        reverse=True,
    )
    student_display_scores = [round_to_display(s.final_score) for s in ranked_students]
    student_ranks = competition_rank(student_display_scores)
    for student, rank in zip(ranked_students, student_ranks, strict=True):
        student.rank = rank
        student.is_tied = student_ranks.count(rank) > 1

    # ---- Seed: 과거 회차 최종점수(가상) -> 다음 회차 자동편성용, 전체 학생 대상 ----
    seed_examples = [
        ("학생A", [Decimal("82.00"), Decimal("88.00"), Decimal("94.00")]),  # 3개, 20/30/50
        ("학생B", [Decimal("84.00"), Decimal("87.00"), Decimal("91.00")]),
        ("학생C", [Decimal("78.00"), Decimal("74.00"), Decimal("70.00")]),
        ("학생D", [Decimal("70.000000"), Decimal("76.500000")]),  # 2개, 뒤에서부터 30/50 재정규화
        ("학생E", [Decimal("75.00"), Decimal("79.00"), Decimal("83.00")]),
        ("학생F", [Decimal("80.00"), Decimal("76.00"), Decimal("72.00")]),
        ("학생G", [Decimal("77.00"), Decimal("77.00")]),
        ("학생H", [Decimal("68.00")]),  # 1개뿐이라 추세 없음
        ("학생I", []),  # 유효 이력 없음 -> 무시드(N/A)
    ]

    def _trend(history):
        """마지막 두 회차를 비교해 상승/하강/유지를 판단한다 (표시용, 순수 장식이 아니라
        '최근 성적이 어느 방향인지'를 바로 읽게 해주는 정보)."""
        if len(history) < 2:
            return None
        return (
            "up" if history[-1] > history[-2] else "down" if history[-1] < history[-2] else "flat"
        )

    seeds = [
        {
            "name": name,
            "history": history,
            "seed": calculate_seed(history),
            "trend": _trend(history),
        }
        for name, history in seed_examples
    ]
    seeds.sort(key=lambda row: (row["seed"] is None, -(row["seed"] or 0)))

    def _by_rank_then_name(row):
        return (
            row.rank is None,
            row.rank if row.rank is not None else 0,
            row.name if hasattr(row, "name") else "",
        )

    no_data_count = sum(
        1
        for s in students
        if s.peer_data_status in {"NO_DATA", "NOT_APPLICABLE"} or s.final_score is None
    )

    return {
        "round_name": "3회차",
        "teams": sorted(teams.values(), key=lambda t: t.number),
        "teams_by_rank": sorted(
            teams.values(), key=lambda t: (t.rank is None, t.rank or 0, t.number)
        ),
        "students": students,
        "students_by_rank": sorted(students, key=_by_rank_then_name),
        "published_at": PUBLISHED_AT,
        "seeds": seeds,
        "winner_team": next((t for t in ranked_teams if t.rank == 1), None),
        "student_count": len(students),
        "team_count": len(teams),
        "no_data_count": no_data_count,
        "top_student": ranked_students[0] if ranked_students else None,
        "top_team": ranked_teams[0] if ranked_teams else None,
    }


def reveal(value, key):
    """공개 게이트를 PUBLISHED_AT의 항목별 시각으로 적용한다 (results.services.reveal_if_published)."""
    return reveal_if_published(value, PUBLISHED_AT.get(key))
