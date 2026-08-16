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
    rank: int | None


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
    final_score: Decimal | None
    rank: int | None


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
    # (이름, 소속 팀, 기대 개인평가 수, 받은 답변 목록)
    student_specs = [
        ("학생A", 1, 2, [[5, 5, 5, 4, 5], [5, 4, 5, 5, 5]]),  # 2/2 COMPLETE, 높은 점수
        ("학생B", 1, 2, [[5, 5, 4, 5, 5], [4, 5, 5, 5, 4]]),  # 2/2 COMPLETE, 학생A와 공동 1위 유도
        ("학생C", 1, 2, [[3, 4, 3, 3, 4]]),  # 1/2 PARTIAL
        ("학생D", 2, 2, []),  # 0/2 NO_DATA -> 개인점수 N/A -> 최종점수도 N/A
        ("학생E", 2, 2, [[4, 4, 3, 4, 4], [4, 4, 4, 3, 4]]),  # 2/2 COMPLETE
        ("학생F", 2, 2, [[3, 3, 4, 3, 3], [4, 3, 3, 4, 3]]),  # 2/2 COMPLETE
        ("학생G", 3, 1, [[4, 4, 4, 4, 4]]),  # 1/1 COMPLETE, 하지만 팀 자체가 N/A라 최종점수는 N/A
        ("학생H", 3, 1, []),  # 0/1 NO_DATA, 팀도 N/A
        ("학생I", 4, 0, []),  # 1인 팀: 평가 대상 없음 -> NOT_APPLICABLE (PR-007)
    ]

    students = []
    for name, team_number, expected_peer, received in student_specs:
        team_score = teams[team_number].team_score
        peer_score = calculate_peer_score(received)
        final_score = calculate_final_score(team_score, peer_score)
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
    for team, rank in zip(ranked_teams, competition_rank(team_display_scores), strict=True):
        team.rank = rank

    ranked_students = sorted(
        (s for s in students if s.final_score is not None),
        key=lambda s: s.final_score,
        reverse=True,
    )
    student_display_scores = [round_to_display(s.final_score) for s in ranked_students]
    for student, rank in zip(
        ranked_students, competition_rank(student_display_scores), strict=True
    ):
        student.rank = rank

    # ---- Seed 데모: 과거 회차 최종점수 예시(가상) -> 다음 회차 자동편성용 ----
    seed_examples = [
        ("학생A", [Decimal("82.00"), Decimal("88.00"), Decimal("94.00")]),  # 3개, 20/30/50
        ("학생D", [Decimal("70.000000"), Decimal("76.500000")]),  # 2개, 뒤에서부터 30/50 재정규화
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

    def _by_rank_then_name(row):
        return (
            row.rank is None,
            row.rank if row.rank is not None else 0,
            row.name if hasattr(row, "name") else "",
        )

    # ---- 튜터 평가 반영 예시 (아직 미확정 - 구축제안서 슬라이드 10/22 참고) ----
    # 튜터 평가 "입력" 기능은 만들지 않고, 반영됐을 때 최종점수 산식이 어떻게 바뀌는지만
    # 학생A의 실제 팀/개인 점수에 가상의 튜터 점수를 대입해 나란히 보여준다.
    tutor_demo_student = students[0]  # 학생A
    tutor_demo_score = Decimal("80.00")
    tutor_example = {
        "student_name": tutor_demo_student.name,
        "team_score": tutor_demo_student.team_score,
        "peer_score": tutor_demo_student.peer_score,
        "tutor_score": tutor_demo_score,
        "final_without_tutor": tutor_demo_student.final_score,
        "final_with_tutor": calculate_final_score(
            tutor_demo_student.team_score, tutor_demo_student.peer_score, tutor_demo_score
        ),
    }

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
        "tutor_example": tutor_example,
    }


def reveal(value, key):
    """공개 게이트를 PUBLISHED_AT의 항목별 시각으로 적용한다 (results.services.reveal_if_published)."""
    return reveal_if_published(value, PUBLISHED_AT.get(key))
