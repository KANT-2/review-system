from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from results.fake_data import build_scenario
from results.services import round_to_display


@dataclass(frozen=True)
class EvaluationProgress:
    label: str
    completed: int
    expected: int

    @property
    def percent(self):
        if self.expected == 0:
            return 100
        return round(self.completed / self.expected * 100)


def _as_five_point(value: Decimal | None):
    if value is None:
        return None
    return round_to_display(value / Decimal("20"))


def build_student_portal(user):
    """개발 시연용 학생 포털 view model.

    rounds/teams/results ORM이 아직 병합되지 않았기 때문에 개발 미리보기가 켜진 환경에서만
    문서화된 DB shape를 따라 계산 코어의 대표 시나리오를 화면에 공급한다. 운영 환경에서는
    임의 데이터를 노출하지 않고 ``None``을 반환해 정상적인 업무 빈 상태를 렌더링한다.
    """

    if not settings.ENABLE_DEV_PREVIEWS:
        return None

    scenario = build_scenario()
    current_user_result = scenario["students"][0]
    current_team = next(
        team for team in scenario["teams"] if team.number == current_user_result.team_number
    )
    now = timezone.now()
    start_at = now - timedelta(days=4)
    end_at = now + timedelta(days=3)
    team_progress = EvaluationProgress("팀 평가", completed=2, expected=3)
    peer_progress = EvaluationProgress("개인 평가", completed=1, expected=2)
    completed = team_progress.completed + peer_progress.completed
    expected = team_progress.expected + peer_progress.expected

    display_name = user.first_name or user.email
    member_names = [display_name, "이수진", "박도현"]
    members = [
        {
            "participant_id": index + 1,
            "student_number_snapshot": f"A{index + 1:03d}",
            "display_name_snapshot": name,
            "is_self": index == 0,
            "evaluation_completed": index == 0,
        }
        for index, name in enumerate(member_names)
    ]

    score_history = [
        {
            "round_name": f"{index}회차",
            "final_score": _as_five_point(score),
            "data_status": "COMPLETE",
        }
        for index, score in enumerate(scenario["seeds"][0]["history"], start=1)
    ]

    return {
        "is_demo": True,
        "round": {
            "title": "3회차 프로젝트 평가",
            "status": "IN_PROGRESS",
            "evaluation_start_at": start_at,
            "evaluation_end_at": end_at,
            "d_day": 3,
        },
        "team": {
            "team_number": current_team.number,
            "name": f"{current_team.number}팀",
            "members": members,
        },
        "progress": {
            "team": team_progress,
            "peer": peer_progress,
            "completed": completed,
            "expected": expected,
            "percent": round(completed / expected * 100),
        },
        "pending_evaluations": [
            {
                "category": "PEER",
                "label": "개인 평가",
                "target": "박도현",
                "description": "같은 팀 구성원에 대한 개인 평가",
            },
            {
                "category": "TEAM",
                "label": "팀 평가",
                "target": "3팀",
                "description": "다른 팀의 프로젝트 결과 평가",
            },
        ],
        "latest_result": {
            "round_name": scenario["round_name"],
            "team_score": _as_five_point(current_user_result.team_score),
            "peer_score": _as_five_point(current_user_result.peer_score),
            "final_score": _as_five_point(current_user_result.final_score),
            "primary_rank": (
                current_user_result.rank
                if scenario["published_at"]["peer_ranking"] is not None
                else None
            ),
            "expected_count": current_user_result.expected_peer_reviews,
            "valid_count": current_user_result.valid_peer_reviews,
            "coverage": current_user_result.peer_coverage,
            "data_status": current_user_result.peer_data_status,
        },
        "score_history": score_history,
        "seed": _as_five_point(scenario["seeds"][0]["seed"]),
    }
