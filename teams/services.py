import random
from collections.abc import Sequence


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
