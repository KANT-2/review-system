"""Pure scoring / ranking / seed calculations owned by the results app.

accounts, rounds, teams, team_reviews and peer_reviews have no models yet, so these functions
take already-fetched raw data (answer lists, prior FinalScores) instead of model instances or
querysets. Once those apps exist, their views/services can call these functions with real data
pulled from the ORM - the signatures below are the stable contract this app commits to; only
the callers change, not this module.
"""

from decimal import ROUND_HALF_UP, Decimal

TEAM_WEIGHT = Decimal("0.4")
PEER_WEIGHT = Decimal("0.6")

# 개인 최종점수의 20/30/50 가중치는 회차를 오래된 순으로 정렬했을 때의 자리를 뜻한다. 3개
# 미만이면 뒤(최근)가 아니라 앞(과거)부터 잘라 재정규화한다: 2개만 있으면 30%+50%가 아니라
# 20%+30%를 재정규화한다. 이 규칙은 예시로 역산해서 확인한 것이라 근거를 남겨둔다.
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


def calculate_team_score(received_answer_sets: list[list[int]]) -> Decimal:
    """팀이 이번 회차에 받은 모든 TeamReview의 평균 점수.

    한 건도 받지 못했으면 평균에서 제외하는 대신 0점으로 취급한다. 그래야 개인 최종점수와
    순위가 항상 정의되고, 다음 회차 Seed 계산에서 '회차 자체에 참여하지 않음'과 구분된다.
    """
    if not received_answer_sets:
        return Decimal("0.00")
    percentages = [score_from_answers(answers) for answers in received_answer_sets]
    return round_to_2dp(sum(percentages) / len(percentages))


def calculate_peer_score(received_answer_sets: list[list[int]]) -> Decimal:
    """학생이 이번 회차에 받은 모든 PeerReview의 평균 점수. 0점 처리 규칙은 팀 점수와 동일하다."""
    if not received_answer_sets:
        return Decimal("0.00")
    percentages = [score_from_answers(answers) for answers in received_answer_sets]
    return round_to_2dp(sum(percentages) / len(percentages))


def calculate_final_score(team_score: Decimal, peer_score: Decimal) -> Decimal:
    """개인 최종점수 = 팀 점수 40% + 개인 점수 60% (TECHNICAL_DECISIONS.md 5번)."""
    return round_to_2dp(team_score * TEAM_WEIGHT + peer_score * PEER_WEIGHT)


def competition_rank(values_descending: list[Decimal]) -> list[int]:
    """동점자를 공동 순위로 매긴다.

    values_descending은 이미 내림차순 정렬되어 있어야 한다. 동점이면 같은 순위를 받고,
    다음 순위는 인원수만큼 건너뛴다 (예: [90, 90, 80] -> [1, 1, 3]).
    """
    ranks: list[int] = []
    for index, value in enumerate(values_descending):
        if index > 0 and value == values_descending[index - 1]:
            ranks.append(ranks[-1])
        else:
            ranks.append(index + 1)
    return ranks


def calculate_seed(recent_final_scores_oldest_first: list[Decimal]) -> Decimal:
    """다음 회차 자동 팀 편성에 쓰일 누적 Seed.

    인자로 받는 리스트는 이미 '개인 최종점수가 존재하는 회차 중 가장 최근 것부터 최대
    3개'를 골라 오래된 순으로 정렬해둔 상태여야 한다. 어느 회차를 포함할지 고르는 건
    rounds/results 조회 로직의 몫이고, 이 함수는 주어진 값들을 어떤 가중치로 섞을지만
    담당한다.

    3개 미만이면 SEED_WEIGHTS를 앞(과거)에서부터 잘라 재정규화한다. 회차 자체가 없어
    리스트에서 빠진 경우와, 회차엔 참여했지만 평가를 못 받아 0점인 경우
    (calculate_team_score/calculate_peer_score가 0을 반환하는 경우)는 다른 상황이다 -
    후자는 정상적인 0점 값으로 리스트에 포함되어야 한다.

    회차 결과 공개 여부와 무관하게 항상 실제 값을 계산한다 (Seed는 내부용 데이터).
    """
    if not recent_final_scores_oldest_first:
        return Decimal("0.00")
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
    취급한다 (TECHNICAL_DECISIONS.md 6, 7번).
    """
    return value if round_is_published else None
