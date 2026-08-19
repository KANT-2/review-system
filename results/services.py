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

Scale and precision (RES-005, docs/DATABASE-DESIGN.md 5.11): every stored score stays on the
same 1~5 scale as the rating answers. Calculations keep six decimal places through the chain -
submission score -> team/peer score -> final score -> seed. Only ``round_to_display`` rounds to
2 decimal places (``ROUND_HALF_UP``) when a value is shown. Rounding every intermediate result
to 2dp would compound rounding error.
"""

import hashlib
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

TEAM_WEIGHT = Decimal("0.4")
PEER_WEIGHT = Decimal("0.6")

# 튜터 평가를 반영하는 회차의 대체 비율 (구축제안서 슬라이드 10 "튜터 평가 반영 시 제안
# 기본값"). 아직 팀 협의 사항으로 미확정이라(제안서 슬라이드 22, 협의 필요 항목 #2) 값이
# 바뀔 수 있어 상수로 분리해뒀다. 튜터 평가 "입력"은 구현되어 있지만(reviews.TutorReview)
# 비율이 확정되기 전까지 채점에는 연결하지 않는다 - calculate_round는 tutor_score를 넘기지
# 않으므로 지금은 항상 팀 40% + 개인 60%로 계산된다.
TEAM_WEIGHT_WITH_TUTOR = Decimal("0.3")
PEER_WEIGHT_WITH_TUTOR = Decimal("0.4")
TUTOR_WEIGHT = Decimal("0.3")

# results_calculation_run.formula_version - 계산 실행마다 어떤 버전의 공식으로 채점했는지
# 남긴다 (docs/DATABASE-DESIGN.md 5.10). 계산 공식이 바뀌면 이 문자열도 올린다.
FORMULA_VERSION = "score-v1"

# 오래된 순 20% / 30% / 50%. 3개 미만이면 뒤(최근)부터 잘라 재정규화한다: 2개면 30%+50%,
# 1개면 50%를 100%로. docs/REFINED-REQUIREMENTS.md AC-10(과거 4.0, 최신 5.0 ->
# (4.0*30 + 5.0*50) / 80 = 4.625)로 확정됨.
SEED_WEIGHTS = [Decimal("0.2"), Decimal("0.3"), Decimal("0.5")]


def round_to_raw(value) -> Decimal:
    """계산 체인 내내 유지하는 정밀도 (``*_raw numeric(9,6)`` 컬럼과 동일한 소수 6자리)."""
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def round_to_display(value) -> Decimal:
    """사용자에게 점수를 보여줄 때만 쓰는 표시 정밀도 (소수 둘째 자리, RES-005)."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def score_from_answers(answers: list[int]) -> Decimal:
    """한 건의 평가 응답을 저장 척도와 같은 1~5점 raw 정밀도로 평균한다."""
    average = sum(answers) / len(answers)
    return round_to_raw(average)


def calculate_team_score(received_answer_sets: list[list[int]]) -> Decimal | None:
    """팀이 이번 회차에 받은 모든 유효 팀 평가 제출의 평균 점수 (raw 정밀도).

    한 건도 받지 못했으면 N/A(``None``)를 반환한다 - 0점으로 대체하지 않는다
    (RES-002, SUB-006).
    """
    if not received_answer_sets:
        return None
    submission_scores = [score_from_answers(answers) for answers in received_answer_sets]
    return round_to_raw(sum(submission_scores) / len(submission_scores))


def calculate_peer_score(received_answer_sets: list[list[int]]) -> Decimal | None:
    """학생이 이번 회차에 받은 모든 유효 개인 평가 제출의 평균 점수 (raw 정밀도). N/A 처리는
    팀 점수와 동일하다 (RES-003, SUB-006)."""
    if not received_answer_sets:
        return None
    submission_scores = [score_from_answers(answers) for answers in received_answer_sets]
    return round_to_raw(sum(submission_scores) / len(submission_scores))


def calculate_final_score(
    team_score: Decimal | None,
    peer_score: Decimal | None,
    tutor_score: Decimal | None = None,
    *,
    team_weight: Decimal | None = None,
    peer_weight: Decimal | None = None,
    tutor_weight: Decimal | None = None,
) -> Decimal | None:
    """개인 최종점수 (raw 정밀도).

    ``tutor_score``를 안 주면(기본값) 팀 점수 40% + 개인 점수 60% (RES-004). 이 회차가
    튜터 평가를 반영하는 회차라 ``tutor_score``가 주어지면 팀 30% + 개인 40% + 튜터 30%로
    바뀐다 - 정확한 비율은 이 모듈의 기본 상수(TEAM_WEIGHT_WITH_TUTOR 등)다.

    ``team_weight``/``peer_weight``/``tutor_weight``는 회차별로 튜터가 설정한 비율
    (rounds.EvaluationRound.team_score_weight 등을 100으로 나눈 값)을 넘길 때 쓴다 - 아무도
    넘기지 않으면(기존 호출부는 전부 그렇다) 이 모듈의 기본 상수를 그대로 쓰므로 기존 동작은
    바뀌지 않는다.

    구성 점수 중 하나라도 N/A(``None``)면 최종점수도 N/A다. ``tutor_score``는 다른
    구성요소와 달리 "이 회차가 튜터 평가를 반영하는지" 자체를 결정하는 파라미터라, None이면
    2요소 산식으로 그냥 폴백한다 - 튜터 평가를 반영하는 회차인데 특정 학생만 튜터 점수가
    빠졌을 때도 N/A로 처리해야 하는지는 아직 확정되지 않았다.
    """
    if team_score is None or peer_score is None:
        return None
    if tutor_score is None:
        tw = team_weight if team_weight is not None else TEAM_WEIGHT
        pw = peer_weight if peer_weight is not None else PEER_WEIGHT
        return round_to_raw(team_score * tw + peer_score * pw)
    tw = team_weight if team_weight is not None else TEAM_WEIGHT_WITH_TUTOR
    pw = peer_weight if peer_weight is not None else PEER_WEIGHT_WITH_TUTOR
    tuw = tutor_weight if tutor_weight is not None else TUTOR_WEIGHT
    return round_to_raw(team_score * tw + peer_score * pw + tutor_score * tuw)


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


def calculate_coverage(expected_count: int, valid_count: int) -> Decimal | None:
    """커버리지 = 유효 제출 수 / 기대 제출 수 (raw 정밀도).

    기대 제출 수가 0이면(NOT_APPLICABLE) 정의되지 않으므로 None을 돌려준다
    (docs/DATABASE-DESIGN.md 5.11: "expected가 0이면 null").
    """
    if expected_count == 0:
        return None
    return round_to_raw(Decimal(valid_count) / Decimal(expected_count))


def competition_rank(values_descending: list[Decimal]) -> list[int]:
    """공개 점수(표시 정밀도) 기준으로 동점자를 공동 순위로 매긴다.

    values_descending은 N/A(``None``)가 이미 제외되고 내림차순 정렬되어 있어야 한다 -
    N/A는 순위 자체에서 빠진다(RES-006). 동점이면 같은 순위를 받고, 다음 순위는 인원수만큼
    건너뛴다 (예: [4.5, 4.5, 4.0, 3.5] -> [1, 1, 3, 4]).
    """
    ranks: list[int] = []
    for index, value in enumerate(values_descending):
        if index > 0 and value == values_descending[index - 1]:
            ranks.append(ranks[-1])
        else:
            ranks.append(index + 1)
    return ranks


def calculate_seed(recent_final_scores_oldest_first: list[Decimal]) -> Decimal | None:
    """다음 회차 자동 팀 편성에 쓰일 Seed (raw 정밀도).

    인자로 받는 리스트는 이미 'N/A가 아닌 최종점수(raw)가 존재하는 회차 중 가장 최근 것부터
    최대 3개'를 골라 오래된 순으로 정렬해둔 상태여야 한다 (docs/DATABASE-DESIGN.md 9번:
    ``EvaluationResult(result_type=INDIVIDUAL).final_score_raw``를 조회). 어느 회차를
    포함할지 고르는 건 호출하는 쪽(rounds/results 조회 로직)의 몫이고, 이 함수는 주어진
    값들을 어떤 가중치로 섞을지만 담당한다.

    유효 이력이 하나도 없으면 '무시드' 상태로 N/A(``None``)를 반환한다 - 0점으로 대체하지
    않는다(TEAM-005, RES-016). N/A인 회차(참여하지 않았거나 평가를 받지 못한 회차)는 애초에
    이 리스트에 들어오지 않아야 한다.

    3개 미만이면 SEED_WEIGHTS를 뒤(최근)에서부터 잘라 재정규화한다 (AC-10).

    회차 결과 공개 여부와 무관하게 항상 실제 값을 계산한다 (RES-017).
    """
    if not recent_final_scores_oldest_first:
        return None
    weights = SEED_WEIGHTS[-len(recent_final_scores_oldest_first) :]
    weight_sum = sum(weights)
    weighted_total = sum(
        score * weight
        for score, weight in zip(recent_final_scores_oldest_first, weights, strict=True)
    )
    return round_to_raw(weighted_total / weight_sum)


def compute_input_digest(valid_submissions: Sequence[tuple[int, str]]) -> str:
    """채점 실행의 입력 지문 (results_calculation_run.input_digest).

    유효 제출 ID와 값의 결정적 SHA-256 해시 - 재채점이 실제로 입력 데이터가 달라져서
    실행된 건지, 아니면 입력이 그대로인데 다시 돌린 건지 감사할 때 쓴다.
    ``valid_submissions``는 (submission_id, value) 쌍의 목록이며, 순서는 상관없다 -
    id 기준으로 정렬한 뒤 해시하므로 같은 입력 집합이면 항상 같은 다이제스트가 나온다.
    """
    canonical = "\n".join(
        f"{submission_id}:{value}" for submission_id, value in sorted(valid_submissions)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reveal_if_published(value, published_at):
    """항목별 결과 공개 게이트.

    회차 전체가 아니라 항목 하나하나가 독립적으로 공개된다 (RES-010, docs/DATABASE-DESIGN.md
    5.10의 ``winner_published_at`` / ``team_ranking_published_at`` / ``my_score_published_at``
    / ``peer_ranking_published_at`` 4개 컬럼). 그래서 이 함수는 회차 단위 boolean이 아니라
    "그 항목이 공개된 시각"(``published_at``, 공개 전이면 ``None``)을 받는다 - 호출하는 쪽이
    4개 항목 각각에 대해 이 함수를 한 번씩 부른다.

    calculate_seed의 결과에는 적용하지 않는다 - Seed는 공개 설정과 무관하게 항상 내부용으로
    취급한다 (RES-017).
    """
    return value if published_at is not None else None
