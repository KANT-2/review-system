import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SeedMetrics:
    """자동편성 후보의 시드 품질지표를 전달한다."""

    team_averages: list[Decimal | None]
    population_standard_deviation: Decimal | None
    seeded_participant_count: int


def distribute_participants(
    participant_ids: Sequence[int],
    team_count: int,
    *,
    rng: random.Random | None = None,
) -> list[list[int]]:
    """참가자를 팀별 인원 차이가 최대 1명이 되도록 무작위 배정한다."""
    participants = list(participant_ids)

    if team_count < 2:
        raise ValueError("team_count must be at least 2")

    if team_count > len(participants):
        raise ValueError("team_count cannot exceed the participant count")

    if len(participants) != len(set(participants)):
        raise ValueError("participant_ids must not contain duplicates")

    # 난수 생성기를 외부에서 전달받으면 테스트에서 같은 배정 결과를 재현할 수 있다.
    random_generator = rng or random.Random()
    random_generator.shuffle(participants)

    teams = [[] for _ in range(team_count)]

    # 섞은 참가자를 순환 배정하면 팀별 인원 차이가 자동으로 최대 1명으로 유지된다.
    for index, participant_id in enumerate(participants):
        team_index = index % team_count
        teams[team_index].append(participant_id)

    return teams


def calculate_seed_metrics(
    teams: Sequence[Sequence[int]],
    seed_scores: Mapping[int, Decimal | None],
) -> SeedMetrics:
    """팀 평균과 모집단 표준편차를 Decimal 정밀도로 계산한다."""
    team_averages: list[Decimal | None] = []
    seeded_participant_count = 0

    for team in teams:
        valid_seed_scores = [
            seed_score
            for participant_id in team
            if (seed_score := seed_scores.get(participant_id)) is not None
        ]

        seeded_participant_count += len(valid_seed_scores)

        if not valid_seed_scores:
            team_averages.append(None)
            continue

        team_average = sum(valid_seed_scores, start=Decimal("0")) / Decimal(len(valid_seed_scores))
        team_averages.append(team_average)

    valid_team_averages = [
        team_average for team_average in team_averages if team_average is not None
    ]

    # 평균을 계산할 수 있는 팀이 둘 미만이면 품질지표를 N/A로 처리한다.
    if len(valid_team_averages) < 2:
        population_standard_deviation = None
    else:
        overall_average = sum(
            valid_team_averages,
            start=Decimal("0"),
        ) / Decimal(len(valid_team_averages))

        squared_deviation_sum = sum(
            ((team_average - overall_average) ** 2 for team_average in valid_team_averages),
            start=Decimal("0"),
        )
        population_variance = squared_deviation_sum / Decimal(len(valid_team_averages))
        population_standard_deviation = population_variance.sqrt()

    return SeedMetrics(
        team_averages=team_averages,
        population_standard_deviation=population_standard_deviation,
        seeded_participant_count=seeded_participant_count,
    )
