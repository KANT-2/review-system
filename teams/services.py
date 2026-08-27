import random
from collections.abc import Collection, Mapping, Sequence
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
    initial_repeated_pair_count: int
    final_repeated_pair_count: int


@dataclass(frozen=True)
class AssignmentValidation:
    """저장 전 팀 구성 검증 결과를 전달한다."""

    team_count: int
    participant_count: int
    team_sizes: list[int]
    has_size_imbalance: bool


class AssignmentValidationError(ValueError):
    """팀 구성이 저장할 수 없는 상태일 때 발생한다."""


class ImbalanceConfirmationRequired(AssignmentValidationError):
    """인원 차이가 큰 수동 편성을 저장하기 전에 재확인이 필요하다."""


class UnassignedParticipantsConfirmationRequired(AssignmentValidationError):
    """일부 참가자가 아직 어느 팀에도 없는 채로 저장하기 전에 재확인이 필요하다.

    회차 시작(rounds.services.round_start_checks)도 이제는 미배정 참가자를 확인 후
    진행할 수 있다 - 그 참가자는 해당 회차 평가·점수 계산에서 빠질 뿐이다.
    """


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
    previous_teammate_pairs: Collection[tuple[int, int]] = (),
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

    for participant_id in seedless_participants:
        team_index = available_team_slots.pop()
        teams[team_index].append(participant_id)

    initial_metrics = calculate_seed_metrics(teams, seed_scores)
    initial_repeated_pair_count = count_repeated_pairs(teams, previous_teammate_pairs)
    initial_teams = [team.copy() for team in teams]
    seed_optimization_count = _optimize_seed_swaps(
        teams,
        seed_scores,
        max_optimizations=max_optimizations,
    )
    repeat_pair_optimization_count = _optimize_repeated_pairs(
        teams,
        seed_scores,
        previous_teammate_pairs,
        max_optimizations=max_optimizations - seed_optimization_count,
        max_allowed_standard_deviation=initial_metrics.population_standard_deviation,
    )

    final_metrics = calculate_seed_metrics(teams, seed_scores)
    final_repeated_pair_count = count_repeated_pairs(teams, previous_teammate_pairs)
    # 권장 최적화가 최초 후보보다 과거 조합을 늘리면 설명 가능한 최초 후보를 유지한다.
    if final_repeated_pair_count > initial_repeated_pair_count:
        teams = initial_teams
        final_metrics = initial_metrics
        final_repeated_pair_count = initial_repeated_pair_count
        seed_optimization_count = 0
        repeat_pair_optimization_count = 0
    return SeedBalancedAssignment(
        teams=teams,
        initial_metrics=initial_metrics,
        final_metrics=final_metrics,
        optimization_count=seed_optimization_count + repeat_pair_optimization_count,
        initial_repeated_pair_count=initial_repeated_pair_count,
        final_repeated_pair_count=final_repeated_pair_count,
    )


def count_repeated_pairs(
    teams: Sequence[Sequence[int]],
    previous_teammate_pairs: Collection[tuple[int, int]],
) -> int:
    """현재 팀 안에서 직전 회차에 함께했던 참가자 쌍의 수를 계산한다."""
    normalized_previous_pairs = {
        frozenset((first_participant_id, second_participant_id))
        for first_participant_id, second_participant_id in previous_teammate_pairs
        if first_participant_id != second_participant_id
    }
    repeated_pair_count = 0
    for team in teams:
        for first_index, first_participant_id in enumerate(team):
            for second_participant_id in team[first_index + 1 :]:
                if (
                    frozenset((first_participant_id, second_participant_id))
                    in normalized_previous_pairs
                ):
                    repeated_pair_count += 1
    return repeated_pair_count


def validate_assignment(
    teams: Sequence[Sequence[int]],
    expected_participant_ids: Sequence[int],
    *,
    imbalance_confirmed: bool = False,
    unassigned_confirmed: bool = False,
) -> AssignmentValidation:
    """저장 요청의 누락·중복·빈 팀·인원 불균형을 검증한다.

    참가자 전원 배정은 저장의 필수조건이 아니다 - 편성 도중에도 저장해 둘 수 있고,
    회차 시작(rounds.services.round_start_checks)도 미배정 참가자를 확인 후 진행할
    수 있다. 그 참가자는 배정 전까지 어느 화면에서도 시작 자체를 막지 않는다.
    """
    expected_participants = list(expected_participant_ids)
    if len(expected_participants) != len(set(expected_participants)):
        raise ValueError("expected_participant_ids must not contain duplicates")
    if len(teams) < 2:
        raise AssignmentValidationError("at least two teams are required")

    team_sizes = [len(team) for team in teams]
    if any(team_size == 0 for team_size in team_sizes):
        raise AssignmentValidationError("empty teams are not allowed")

    assigned_participants = [participant_id for team in teams for participant_id in team]
    duplicate_participants = _find_duplicate_participants(assigned_participants)
    if duplicate_participants:
        raise AssignmentValidationError(
            f"duplicate participants are not allowed: {duplicate_participants}"
        )

    expected_participant_set = set(expected_participants)
    assigned_participant_set = set(assigned_participants)
    missing_participants = sorted(expected_participant_set - assigned_participant_set)
    unexpected_participants = sorted(assigned_participant_set - expected_participant_set)
    # 회차에 속하지 않는 참가자가 섞여 들어온 건 확인으로 넘어갈 수 있는 상황이 아니라
    # 데이터가 어긋난 것이다 - 항상 막는다.
    if unexpected_participants:
        raise AssignmentValidationError(
            f"unexpected participants were assigned: {unexpected_participants}"
        )
    # 반면 일부만 배정하고 나머지는 나중에 배정하려는 건 정상적인 작업 흐름이라,
    # 명시적으로 확인한 요청에서만 통과시킨다.
    if missing_participants and not unassigned_confirmed:
        raise UnassignedParticipantsConfirmationRequired(
            f"participants are not yet assigned to any team: {missing_participants}"
        )

    has_size_imbalance = max(team_sizes) - min(team_sizes) > 1
    # 수동 조정은 허용하되, 큰 인원 차이는 사용자가 경고를 확인한 요청에서만 저장한다.
    if has_size_imbalance and not imbalance_confirmed:
        raise ImbalanceConfirmationRequired("team size imbalance requires explicit confirmation")

    return AssignmentValidation(
        team_count=len(teams),
        participant_count=len(assigned_participants),
        team_sizes=team_sizes,
        has_size_imbalance=has_size_imbalance,
    )


def _validate_assignment_input(participant_ids: Sequence[int], team_count: int) -> None:
    """자동편성 입력을 검사한다.

    AssignmentValidationError는 ValueError의 하위형이라 기존 호출부는 그대로 동작하고,
    화면 쪽은 500 대신 무엇이 잘못됐는지 읽을 수 있는 400을 받는다.
    """
    if team_count < 2:
        raise AssignmentValidationError("팀은 2개 이상이어야 합니다.")
    if team_count > len(participant_ids):
        raise AssignmentValidationError(
            f"배치할 학생이 {len(participant_ids)}명뿐이라 {team_count}개 팀으로 나눌 수 없습니다."
        )
    if len(participant_ids) != len(set(participant_ids)):
        raise AssignmentValidationError("같은 학생이 두 번 들어 있습니다.")


def _find_duplicate_participants(participant_ids: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for participant_id in participant_ids:
        if participant_id in seen:
            duplicates.add(participant_id)
        seen.add(participant_id)
    return sorted(duplicates)


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
                    if seed_scores.get(first_participant_id) is None:
                        continue
                    for second_member_index, second_participant_id in enumerate(second_team):
                        if seed_scores.get(second_participant_id) is None:
                            continue
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


def _optimize_repeated_pairs(
    teams: list[list[int]],
    seed_scores: Mapping[int, Decimal | None],
    previous_teammate_pairs: Collection[tuple[int, int]],
    *,
    max_optimizations: int,
    max_allowed_standard_deviation: Decimal | None,
) -> int:
    current_metrics = calculate_seed_metrics(teams, seed_scores)
    current_standard_deviation = current_metrics.population_standard_deviation
    current_repeated_pair_count = count_repeated_pairs(teams, previous_teammate_pairs)
    optimization_count = 0

    while optimization_count < max_optimizations and current_repeated_pair_count > 0:
        best_swap: tuple[int, int, int, int] | None = None
        best_repeated_pair_count = current_repeated_pair_count
        best_standard_deviation = current_standard_deviation

        for first_team_index, first_team in enumerate(teams):
            for second_team_index in range(first_team_index + 1, len(teams)):
                second_team = teams[second_team_index]
                for first_member_index, first_participant_id in enumerate(first_team):
                    for second_member_index, second_participant_id in enumerate(second_team):
                        first_team[first_member_index] = second_participant_id
                        second_team[second_member_index] = first_participant_id
                        candidate_metrics = calculate_seed_metrics(teams, seed_scores)
                        candidate_repeated_pair_count = count_repeated_pairs(
                            teams,
                            previous_teammate_pairs,
                        )
                        first_team[first_member_index] = first_participant_id
                        second_team[second_member_index] = second_participant_id

                        candidate_standard_deviation = (
                            candidate_metrics.population_standard_deviation
                        )
                        keeps_seed_balance = max_allowed_standard_deviation is None or (
                            candidate_standard_deviation is not None
                            and candidate_standard_deviation <= max_allowed_standard_deviation
                        )
                        if (
                            keeps_seed_balance
                            and candidate_repeated_pair_count < best_repeated_pair_count
                        ):
                            best_repeated_pair_count = candidate_repeated_pair_count
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
        current_repeated_pair_count = best_repeated_pair_count
        current_standard_deviation = best_standard_deviation
        optimization_count += 1

    return optimization_count
