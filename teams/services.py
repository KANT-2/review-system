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


@dataclass(frozen=True)
class SeedBalancedAssignment:
    """자동편성 결과와 개선 전후 품질지표를 전달한다."""

    teams: list[list[int]]
    initial_metrics: SeedMetrics
    final_metrics: SeedMetrics
    optimization_count: int


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


def create_seed_balanced_assignment(
    participant_ids: Sequence[int],
    seed_scores: Mapping[int, Decimal | None],
    team_count: int,
    *,
    rng: random.Random | None = None,
    max_optimizations: int = 100,
) -> SeedBalancedAssignment:
    """인원 균형을 유지하며 시드 표준편차가 나빠지지 않는 후보를 만든다."""
    participants = list(participant_ids)
    _validate_assignment_input(participants, team_count)
    if not 0 <= max_optimizations <= 100:
        raise ValueError("max_optimizations must be between 0 and 100")

    random_generator = rng or random.Random()
    seeded_participants = [
        participant_id
        for participant_id in participants
        if seed_scores.get(participant_id) is not None
    ]
    seedless_participants = [
        participant_id for participant_id in participants if seed_scores.get(participant_id) is None
    ]
    random_generator.shuffle(seeded_participants)
    random_generator.shuffle(seedless_participants)

    target_sizes = _calculate_target_sizes(len(participants), team_count)
    available_team_slots = _create_randomized_team_slots(target_sizes, random_generator)
    teams = [[] for _ in range(team_count)]

    # 시드 없는 참가자는 0점으로 계산하지 않고, 시드 참가자를 배치한 뒤 남은 자리를 채운다.
    for participant_id in seeded_participants:
        team_index = available_team_slots.pop()
        teams[team_index].append(participant_id)

    initial_metrics = calculate_seed_metrics(teams, seed_scores)
    optimization_count = _optimize_seed_swaps(
        teams,
        seed_scores,
        max_optimizations=max_optimizations,
    )

    for participant_id in seedless_participants:
        team_index = available_team_slots.pop()
        teams[team_index].append(participant_id)

    final_metrics = calculate_seed_metrics(teams, seed_scores)
    return SeedBalancedAssignment(
        teams=teams,
        initial_metrics=initial_metrics,
        final_metrics=final_metrics,
        optimization_count=optimization_count,
    )


def _validate_assignment_input(participant_ids: Sequence[int], team_count: int) -> None:
    if team_count < 2:
        raise ValueError("team_count must be at least 2")
    if team_count > len(participant_ids):
        raise ValueError("team_count cannot exceed the participant count")
    if len(participant_ids) != len(set(participant_ids)):
        raise ValueError("participant_ids must not contain duplicates")


def _calculate_target_sizes(participant_count: int, team_count: int) -> list[int]:
    minimum_size, larger_team_count = divmod(participant_count, team_count)
    return [
        minimum_size + (1 if team_index < larger_team_count else 0)
        for team_index in range(team_count)
    ]


def _create_randomized_team_slots(
    target_sizes: Sequence[int],
    random_generator: random.Random,
) -> list[int]:
    team_slots: list[int] = []
    # 각 순환에서 모든 팀을 한 번씩 배치해 시드 참가자가 특정 팀에 몰리지 않게 한다.
    for position in range(max(target_sizes)):
        round_team_indices = [
            team_index
            for team_index, target_size in enumerate(target_sizes)
            if position < target_size
        ]
        random_generator.shuffle(round_team_indices)
        team_slots.extend(round_team_indices)
    team_slots.reverse()
    return team_slots


def _optimize_seed_swaps(
    teams: list[list[int]],
    seed_scores: Mapping[int, Decimal | None],
    *,
    max_optimizations: int,
) -> int:
    current_metrics = calculate_seed_metrics(teams, seed_scores)
    if current_metrics.population_standard_deviation is None:
        return 0

    optimization_count = 0
    while optimization_count < max_optimizations:
        best_swap: tuple[int, int, int, int] | None = None
        best_standard_deviation = current_metrics.population_standard_deviation

        for first_team_index, first_team in enumerate(teams):
            for second_team_index in range(first_team_index + 1, len(teams)):
                second_team = teams[second_team_index]
                for first_member_index, first_participant_id in enumerate(first_team):
                    for second_member_index, second_participant_id in enumerate(second_team):
                        first_team[first_member_index] = second_participant_id
                        second_team[second_member_index] = first_participant_id
                        candidate_metrics = calculate_seed_metrics(teams, seed_scores)
                        first_team[first_member_index] = first_participant_id
                        second_team[second_member_index] = second_participant_id

                        candidate_standard_deviation = (
                            candidate_metrics.population_standard_deviation
                        )
                        if (
                            candidate_standard_deviation is not None
                            and candidate_standard_deviation < best_standard_deviation
                        ):
                            best_standard_deviation = candidate_standard_deviation
                            best_swap = (
                                first_team_index,
                                first_member_index,
                                second_team_index,
                                second_member_index,
                            )

        if best_swap is None:
            break

        (
            first_team_index,
            first_member_index,
            second_team_index,
            second_member_index,
        ) = best_swap
        (
            teams[first_team_index][first_member_index],
            teams[second_team_index][second_member_index],
        ) = (
            teams[second_team_index][second_member_index],
            teams[first_team_index][first_member_index],
        )
        current_metrics = calculate_seed_metrics(teams, seed_scores)
        optimization_count += 1

    return optimization_count
