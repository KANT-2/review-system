"""Pure scoring / ranking / seed calculations owned by the results app.

accounts, rounds, teams and reviews have no models yet, so these functions take already-fetched
raw data (answer lists, prior FinalScores, expected/valid counts) instead of model instances or
querysets. Once those apps exist, their views/services can call these functions with real data
pulled from the ORM - the signatures below are the stable contract this app commits to; only the
callers change, not this module.

N/A vs 0 (docs/REFINED-REQUIREMENTS.md RES-004/RES-006/SUB-005/SUB-006/TEAM-005/RES-016): a team
or student that received zero valid evaluations is N/A (represented here as ``None``), not a
real 0.00 score. N/A propagates through FinalScore, is excluded from ranking, and is excluded
from Seed history - it is never averaged in as 0. This supersedes this project's earlier
ADR-0001 ("missing evaluation data scores as 0"), which predates this refined spec.
"""

from decimal import ROUND_HALF_UP, Decimal

TEAM_WEIGHT = Decimal("0.4")
PEER_WEIGHT = Decimal("0.6")

# 오래된 순 20% / 30% / 50%. 3개 미만일 때 어느 쪽에서 잘라 재정규화할지는 아직 문서 간
# 결론이 다르다:
#   - 이 프로젝트 초기 스펙의 예시(1회차=80, 2회차=90 -> 86)는 앞(과거)부터 자르는 걸
#     전제한다: 80*(20/50) + 90*(30/50) = 86.
#   - docs/REFINED-REQUIREMENTS.md AC-10(과거 4.0, 최신 5.0 -> 4.625)은 뒤(최근)부터
#     자르는 걸 전제한다: (4.0*30 + 5.0*50) / 80 = 4.625.
# 둘 다 각자 문서 안에서는 예시로 검증되는 자기 일관적인 규칙이라 코드만으로는 어느 쪽이
# 맞는지 판단할 수 없다. 현재 구현은 이전부터 검증해온 앞쪽 자르기를 유지하고 있으며, 팀
# 논의 후 확정되면 이 상수와 calculate_seed()를 함께 갱신해야 한다.
SEED_WEIGHTS = [Decimal("0.2"), Decimal("0.3"), Decimal("0.5")]


def round_to_2dp(value) -> Decimal:
    """점수 계산 결과를 저장/비교할 때 쓰는 내부 정밀도."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_to_1dp(value: Decimal) -> Decimal:
    """화면에 점수를 보여줄 때 쓰는 표시 정밀도."""
    return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def score_from_answers(answers: list[int]) -> Decimal:
    """한 건의 평가 응답(1~5점 문항 목록)을 0~100점으로 환산한다."""
    average = sum(answers) / len(answers)
    return round_to_2dp(average / 5 * 100)


def calculate_team_score(received_answer_sets: list[list[int]]) -> Decimal | None:
    """팀이 이번 회차에 받은 모든 유효 팀 평가 제출의 평균 점수.

    한 건도 받지 못했으면 N/A(``None``)를 반환한다 - 0점으로 대체하지 않는다
    (RES-002, SUB-006).
    """
    if not received_answer_sets:
        return None
    percentages = [score_from_answers(answers) for answers in received_answer_sets]
    return round_to_2dp(sum(percentages) / len(percentages))


def calculate_peer_score(received_answer_sets: list[list[int]]) -> Decimal | None:
    """학생이 이번 회차에 받은 모든 유효 개인 평가 제출의 평균 점수. N/A 처리는 팀 점수와 동일하다
    (RES-003, SUB-006)."""
    if not received_answer_sets:
        return None
    percentages = [score_from_answers(answers) for answers in received_answer_sets]
    return round_to_2dp(sum(percentages) / len(percentages))


def calculate_final_score(team_score: Decimal | None, peer_score: Decimal | None) -> Decimal | None:
    """개인 최종점수 = 팀 점수 40% + 개인 점수 60%.

    두 구성 점수 중 하나라도 N/A(``None``)면 최종점수도 N/A다 (RES-004).
    """
    if team_score is None or peer_score is None:
        return None
    return round_to_2dp(team_score * TEAM_WEIGHT + peer_score * PEER_WEIGHT)


def determine_data_status(expected_count: int, valid_count: int) -> str:
    """SUB-004의 데이터 상태 판정표.

    호출하는 쪽에서 기대 제출 수(expected_count)와 유효 제출 수(valid_count)를 넘겨주면
    'NOT_APPLICABLE' | 'NO_DATA' | 'PARTIAL' | 'COMPLETE' 중 하나를 돌려준다. expected_count가
    0이면(예: 1인 팀의 개인 평가처럼 애초에 평가 대상이 없는 경우) NOT_APPLICABLE이다.
    """
    if expected_count == 0:
        return "NOT_APPLICABLE"
    if valid_count == 0:
        return "NO_DATA"
    if valid_count < expected_count:
        return "PARTIAL"
    return "COMPLETE"


def competition_rank(values_descending: list[Decimal]) -> list[int]:
    """동점자를 공동 순위로 매긴다.

    values_descending은 N/A(``None``)가 이미 제외되고 내림차순 정렬되어 있어야 한다 -
    N/A는 순위 자체에서 빠진다(RES-006). 동점이면 같은 순위를 받고, 다음 순위는 인원수만큼
    건너뛴다 (예: [90, 90, 80] -> [1, 1, 3]).
    """
    ranks: list[int] = []
    for index, value in enumerate(values_descending):
        if index > 0 and value == values_descending[index - 1]:
            ranks.append(ranks[-1])
        else:
            ranks.append(index + 1)
    return ranks


def calculate_seed(recent_final_scores_oldest_first: list[Decimal]) -> Decimal | None:
    """다음 회차 자동 팀 편성에 쓰일 Seed.

    인자로 받는 리스트는 이미 'N/A가 아닌 최종점수가 존재하는 회차 중 가장 최근 것부터
    최대 3개'를 골라 오래된 순으로 정렬해둔 상태여야 한다. 어느 회차를 포함할지 고르는 건
    호출하는 쪽(rounds/results 조회 로직)의 몫이고, 이 함수는 주어진 값들을 어떤 가중치로
    섞을지만 담당한다.

    유효 이력이 하나도 없으면 '무시드' 상태로 N/A(``None``)를 반환한다 - 0점으로 대체하지
    않는다(TEAM-005, RES-016). N/A인 회차(참여하지 않았거나 평가를 받지 못한 회차)는애초에
    이 리스트에 들어오지 않아야 한다.

    3개 미만일 때의 가중치 재정규화 방향은 아직 확정되지 않았다 - 모듈 상단 SEED_WEIGHTS
    주석 참고.

    회차 결과 공개 여부와 무관하게 항상 실제 값을 계산한다 (RES-017).
    """
    if not recent_final_scores_oldest_first:
        return None
    weights = SEED_WEIGHTS[: len(recent_final_scores_oldest_first)]
    weight_sum = sum(weights)
    weighted_total = sum(
        score * weight
        for score, weight in zip(recent_final_scores_oldest_first, weights, strict=True)
    )
    return round_to_2dp(weighted_total / weight_sum)


def reveal_if_published(value, round_is_published: bool):
    """결과 공개 여부 게이트. 회차가 비공개면 None을 돌려줘 노출을 막는다.

    calculate_seed의 결과에는 적용하지 않는다 - Seed는 공개 설정과 무관하게 항상 내부용으로
    취급한다 (RES-017).
    """
    return value if round_is_published else None
