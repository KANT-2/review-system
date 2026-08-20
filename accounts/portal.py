from dataclasses import dataclass
from math import ceil

from django.db.models import Avg, Q
from django.utils import timezone

from results.models import CalculationRun, EvaluationResult
from results.services import round_to_display
from reviews.models import ReviewAnswer, ReviewSubmission, TutorReviewAnswer, TutorTeamReviewAnswer
from reviews.services import current_participation, peer_targets, team_targets
from rounds.models import RoundParticipant, TemplateQuestion

COMPETENCY_LABELS = dict(TemplateQuestion.Competency.choices)


@dataclass(frozen=True)
class EvaluationProgress:
    label: str
    completed: int
    expected: int

    @property
    def percent(self):
        return 100 if self.expected == 0 else round(self.completed / self.expected * 100)


def _published_result_rows(user, limit=None):
    """공개된 개인 결과 - 최신 회차가 앞에 온다.

    limit을 안 주면 전체를 돌려준다(회차 선택 목록, 점수 막대그래프용).
    """
    qs = (
        EvaluationResult.objects.filter(
            result_type=EvaluationResult.ResultType.INDIVIDUAL,
            participant__user=user,
            calculation_run__is_active=True,
            calculation_run__my_score_published_at__isnull=False,
        )
        .select_related("calculation_run__round")
        .order_by("-calculation_run__round__completed_at")
    )
    return list(qs[:limit]) if limit else list(qs)


def _team_coverage(result):
    """이 결과가 속한 팀의 팀평가 응답 현황 - 개인 결과 행에는 없어서 TEAM 행을 따로 찾는다."""
    membership = getattr(result.participant, "team_membership", None)
    if membership is None:
        return None, None
    team_result = result.calculation_run.results.filter(
        result_type=EvaluationResult.ResultType.TEAM, team_id=membership.team_id
    ).first()
    if team_result is None:
        return None, None
    return team_result.valid_count, team_result.expected_count


def _serialize_result(result):
    run = result.calculation_run
    team_valid_count, team_expected_count = _team_coverage(result)
    return {
        "round_id": run.round_id,
        "round_name": run.round.title,
        "evaluation_start_at": run.round.evaluation_start_at,
        "evaluation_end_at": run.round.evaluation_end_at,
        "team_score": result.team_score_raw,
        "peer_score": result.peer_score_raw,
        "tutor_score": result.tutor_score_raw,
        "final_score": result.final_score_raw,
        "primary_rank": result.primary_rank if run.peer_ranking_published_at else None,
        "expected_count": result.expected_count,
        "valid_count": result.valid_count,
        "coverage": result.coverage,
        "data_status": result.data_status,
        "team_valid_count": team_valid_count,
        "team_expected_count": team_expected_count,
        "team_score_weight": run.round.team_score_weight,
        "personal_score_weight": run.round.personal_score_weight,
        "tutor_score_weight": run.round.tutor_score_weight,
    }


def _latest_result(user):
    rows = _published_result_rows(user, limit=1)
    return _serialize_result(rows[0]) if rows else None


def _published_participants(user):
    """점수 공개가 끝난 회차들의 내 참가 기록 - 역량 집계와 피드백 목록이 공통으로 쓴다."""
    return list(
        RoundParticipant.objects.filter(
            user=user,
            round__calculation_runs__is_active=True,
            round__calculation_runs__my_score_published_at__isnull=False,
        )
        .select_related("round", "team_membership")
        .distinct()
    )


def _competency_scores(user):
    """공개된 회차에서 내가 받은 역량 태그 문항의 평균 점수 - 역량 코드별 평균."""
    participants = _published_participants(user)
    if not participants:
        return {}
    participant_ids = [participant.pk for participant in participants]
    team_ids = [
        participant.team_membership.team_id
        for participant in participants
        if hasattr(participant, "team_membership")
    ]
    rows = (
        ReviewAnswer.objects.filter(rating_value__isnull=False)
        .exclude(question__competency="")
        .filter(
            Q(submission__target_participant_id__in=participant_ids)
            | Q(submission__target_team_id__in=team_ids)
        )
        .values("question__competency")
        .annotate(avg_score=Avg("rating_value"))
    )
    return {row["question__competency"]: float(row["avg_score"]) for row in rows}


def _competency_radar(user):
    """5대 역량 레이더차트 데이터 - 강점 상위 2개, 보완 필요 하위 2개를 함께 계산한다.

    역량 태그가 없는 문항은 애초에 집계에 안 들어가므로, 응답이 있는 역량만 강점·보완
    후보가 된다(REFINED-REQUIREMENTS.md MVP 경계를 넘어선 기능 - CONTEXT.md 참고).
    """
    scores = _competency_scores(user)
    entries = [
        {
            "code": code,
            "label": label,
            "score": round(scores[code], 1) if code in scores else None,
        }
        for code, label in COMPETENCY_LABELS.items()
    ]
    scored = sorted(
        (entry for entry in entries if entry["score"] is not None),
        key=lambda entry: entry["score"],
        reverse=True,
    )
    strengths = scored[:2]
    strength_codes = {entry["code"] for entry in strengths}
    weaknesses = sorted(
        (entry for entry in scored if entry["code"] not in strength_codes),
        key=lambda entry: entry["score"],
    )[:2]
    return {
        "entries": entries,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "has_data": bool(scored),
    }


def _feedback_items(user):
    """공개된 회차에서 내가 받은 주관식 피드백 - templates/base.html의 전역 '통합 피드백
    센터' 모달이 기대하는 tutor/team/peer 구조에 맞춘다(그 모달은 이미 만들어져 있었지만
    feedbacks 컨텍스트가 어디서도 채워지지 않아 항상 비어 있었다).

    동료(개인·팀) 피드백은 익명 처리하고, 튜터 피드백만 실명으로 보여준다. 점수 공개
    (my_score_published_at)와 같은 기준을 쓴다 - 점수는 비공개인데 피드백만 먼저 보이면
    튜터 검토 전에 원문이 노출되는 셈이라 안 된다.
    """
    participants = _published_participants(user)
    if not participants:
        return {"tutor": [], "team": [], "peer": []}
    participant_ids = [participant.pk for participant in participants]
    round_name_by_participant = {
        participant.pk: participant.round.title for participant in participants
    }
    team_ids = []
    round_name_by_team = {}
    team_name_by_team = {}
    for participant in participants:
        membership = getattr(participant, "team_membership", None)
        if membership is None:
            continue
        team_ids.append(membership.team_id)
        round_name_by_team[membership.team_id] = participant.round.title
        team_name_by_team[membership.team_id] = membership.team.name

    def _date(created_at):
        return created_at.strftime("%Y-%m-%d")

    peer_rows = list(
        ReviewAnswer.objects.filter(
            submission__review_type=ReviewSubmission.ReviewType.PEER,
            submission__target_participant_id__in=participant_ids,
            question__response_type=TemplateQuestion.ResponseType.TEXT,
        )
        .exclude(text_value="")
        .select_related("submission")
    )
    peer = [
        {
            "author": "익명",
            "week": round_name_by_participant.get(row.submission.target_participant_id, ""),
            "date": _date(row.created_at),
            "content": row.text_value,
            "created_at": row.created_at,
        }
        for row in peer_rows
    ]

    team_rows = list(
        ReviewAnswer.objects.filter(
            submission__review_type=ReviewSubmission.ReviewType.TEAM,
            submission__target_team_id__in=team_ids,
            question__response_type=TemplateQuestion.ResponseType.TEXT,
        )
        .exclude(text_value="")
        .select_related("submission")
    )
    team = [
        {
            "team_name": team_name_by_team.get(row.submission.target_team_id, ""),
            "week": round_name_by_team.get(row.submission.target_team_id, ""),
            "date": _date(row.created_at),
            "content": row.text_value,
            "created_at": row.created_at,
        }
        for row in team_rows
    ]

    tutor_personal_rows = list(
        TutorReviewAnswer.objects.filter(
            review__target_participant_id__in=participant_ids,
            question__response_type=TemplateQuestion.ResponseType.TEXT,
        )
        .exclude(text_value="")
        .select_related("review__evaluator")
    )
    tutor_team_rows = list(
        TutorTeamReviewAnswer.objects.filter(
            review__target_team_id__in=team_ids,
            question__response_type=TemplateQuestion.ResponseType.TEXT,
        )
        .exclude(text_value="")
        .select_related("review__evaluator")
    )
    tutor = [
        {
            "author": row.review.evaluator.first_name or "튜터",
            "week": round_name_by_participant.get(row.review.target_participant_id, ""),
            "date": _date(row.created_at),
            "content": row.text_value,
            "created_at": row.created_at,
        }
        for row in tutor_personal_rows
    ] + [
        {
            "author": row.review.evaluator.first_name or "튜터",
            "week": round_name_by_team.get(row.review.target_team_id, ""),
            "date": _date(row.created_at),
            "content": row.text_value,
            "created_at": row.created_at,
        }
        for row in tutor_team_rows
    ]

    peer.sort(key=lambda item: item["created_at"], reverse=True)
    team.sort(key=lambda item: item["created_at"], reverse=True)
    tutor.sort(key=lambda item: item["created_at"], reverse=True)
    return {"tutor": tutor, "team": team, "peer": peer}


def _feedback_preview(feedback_items, limit=3):
    """프로필 카드에 보여줄 최근 피드백 미리보기 - 유형 안 가리고 최신순으로 합친다."""
    combined = (
        [{**item, "label": item["author"]} for item in feedback_items["peer"]]
        + [
            {**item, "label": f"{item['team_name']} 피드백" if item["team_name"] else "팀 피드백"}
            for item in feedback_items["team"]
        ]
        + [{**item, "label": item["author"]} for item in feedback_items["tutor"]]
    )
    combined.sort(key=lambda item: item["created_at"], reverse=True)
    return combined[:limit]


def round_result_csv_rows(user, round_id):
    """회차 결과 CSV 다운로드용 - 공개된 결과가 아니면 None을 돌려준다."""
    result = next(
        (row for row in _published_result_rows(user) if row.calculation_run.round_id == round_id),
        None,
    )
    if result is None:
        return None
    data = _serialize_result(result)
    return {
        "round_name": data["round_name"],
        "rows": [
            ("항목", "값"),
            ("회차", data["round_name"]),
            ("팀 점수", data["team_score"]),
            ("개인 점수", data["peer_score"]),
            ("최종 점수", data["final_score"]),
            ("개인 순위", data["primary_rank"] if data["primary_rank"] else "비공개"),
            ("개인 평가 응답", f"{data['valid_count']}/{data['expected_count']}"),
            ("데이터 상태", data["data_status"]),
        ],
    }


def _score_delta(current, previous):
    """전 회차 대비 변화 - 방향과 변화폭을 함께 돌려준다(표시 정밀도 기준).

    두 회차 모두 점수가 있어야 비교가 성립한다. 한쪽이라도 N/A면 None을 돌려준다.
    """
    if current is None or previous is None:
        return None
    delta = round_to_display(current) - round_to_display(previous)
    if delta > 0:
        return {"direction": "up", "value": delta}
    if delta < 0:
        return {"direction": "down", "value": -delta}
    return {"direction": "flat", "value": delta}


def _published_team_winner(round_id):
    """그 회차의 1위 팀 - 튜터가 '팀 1위'를 공개한 경우에만 돌려준다."""
    run = CalculationRun.objects.filter(
        round_id=round_id, is_active=True, winner_published_at__isnull=False
    ).first()
    if not run:
        return None
    winner = (
        run.results.filter(result_type=EvaluationResult.ResultType.TEAM, primary_rank=1)
        .select_related("team")
        .first()
    )
    if not winner:
        return None
    return {"name": winner.team.name, "score": winner.team_score_raw}


def build_student_result_portal(user, *, selected_round_id=None):
    """마이페이지 결과 영역 - 회차를 골라 그 회차 결과와 전 회차 대비 변화를 함께 본다.

    '내 결과' 화면에 있던 내용을 여기로 합쳤다. 개인 순위는 넣지 않는다.
    """
    rows = _published_result_rows(user)
    if not rows:
        return None
    serialized = [_serialize_result(result) for result in rows]
    trend = [
        {
            "round_id": row["round_id"],
            "round_name": row["round_name"],
            "team_score": float(row["team_score"]) if row["team_score"] is not None else None,
            "peer_score": float(row["peer_score"]) if row["peer_score"] is not None else None,
            # tutor_score_weight가 0인 회차는 애초에 튜터 점수를 집계하지 않아 항상 None이라,
            # 그래프에서도 자연히 그 회차만 비어 보인다(별도 분기 없이 0점과 구분됨).
            "tutor_score": float(row["tutor_score"]) if row["tutor_score"] is not None else None,
            "final_score": float(row["final_score"]) if row["final_score"] is not None else None,
            "team_valid_count": row["team_valid_count"],
            "team_expected_count": row["team_expected_count"],
            "peer_valid_count": row["valid_count"],
            "peer_expected_count": row["expected_count"],
            "team_score_weight": row["team_score_weight"],
            "personal_score_weight": row["personal_score_weight"],
            "tutor_score_weight": row["tutor_score_weight"],
        }
        for row in reversed(serialized)
    ]
    index = 0
    if selected_round_id is not None:
        index = next(
            (
                position
                for position, row in enumerate(serialized)
                if row["round_id"] == selected_round_id
            ),
            0,
        )
    selected = serialized[index]
    # 목록은 최신 회차가 앞이므로 바로 다음 항목이 직전 회차다.
    previous = serialized[index + 1] if index + 1 < len(serialized) else None
    feedback_items = _feedback_items(user)
    feedback_items["recent"] = _feedback_preview(feedback_items)
    return {
        "is_demo": False,
        "selected": selected,
        "previous": previous,
        "deltas": {
            key: _score_delta(selected[key], previous[key] if previous else None)
            for key in ("team_score", "peer_score", "final_score")
        },
        "team_winner": _published_team_winner(selected["round_id"]),
        "round_options": [
            {"round_id": row["round_id"], "round_name": row["round_name"]} for row in serialized
        ],
        "score_trend": trend,
        "competency": _competency_radar(user),
        "feedback": feedback_items,
    }


def build_student_portal(user):
    participant = current_participation(user)
    if not participant:
        return None
    round_obj = participant.round
    team_rows = team_targets(participant)
    peer_rows = peer_targets(participant)
    team_progress = EvaluationProgress(
        "팀 평가", sum(row.completed for row in team_rows), len(team_rows)
    )
    peer_progress = EvaluationProgress(
        "개인 평가", sum(row.completed for row in peer_rows), len(peer_rows)
    )
    completed = team_progress.completed + peer_progress.completed
    expected = team_progress.expected + peer_progress.expected
    membership = getattr(participant, "team_membership", None)
    team = membership.team if membership else None
    peer_completed_ids = {row.pk for row in peer_rows if row.completed}
    members = []
    if team:
        members = [
            {
                "participant_id": member.participant_id,
                "student_number_snapshot": member.participant.student_number_snapshot,
                "display_name_snapshot": member.participant.display_name_snapshot,
                "is_self": member.participant_id == participant.pk,
                "evaluation_completed": (
                    member.participant_id == participant.pk
                    or member.participant_id in peer_completed_ids
                ),
            }
            for member in team.memberships.select_related("participant")
        ]

    def _evaluation_rows(rows, *, category, label, completed):
        return [
            {
                "category": category,
                "label": label,
                "target": row.label,
                "description": row.description,
                "target_id": row.pk,
                "url_name": row.url_name,
            }
            for row in rows
            if row.completed is completed
        ]

    pending = _evaluation_rows(
        team_rows, category="TEAM", label="팀 평가", completed=False
    ) + _evaluation_rows(peer_rows, category="PEER", label="개인 평가", completed=False)
    # 제출한 평가도 함께 보여준다 - 무엇을 이미 냈는지 화면에서 확인할 수 있어야 한다.
    done = _evaluation_rows(
        team_rows, category="TEAM", label="팀 평가", completed=True
    ) + _evaluation_rows(peer_rows, category="PEER", label="개인 평가", completed=True)
    remaining = round_obj.evaluation_end_at - timezone.now()
    d_day = max(ceil(remaining.total_seconds() / 86400), 0)
    return {
        "is_demo": False,
        "round": {
            "title": round_obj.title,
            "status": round_obj.get_status_display(),
            "evaluation_start_at": round_obj.evaluation_start_at,
            "evaluation_end_at": round_obj.evaluation_end_at,
            "d_day": d_day,
            # 남은 평가가 있는데 마감이 하루 안쪽이면 화면에서 눈에 띄게 표시한다.
            "is_urgent": bool(pending) and d_day <= 1,
        },
        "team": {
            "team_number": team.team_number if team else None,
            "name": team.name if team else "팀 편성 전",
            "members": members,
        },
        "progress": {
            "team": team_progress,
            "peer": peer_progress,
            "completed": completed,
            "expected": expected,
            "percent": 100 if expected == 0 else round(completed / expected * 100),
        },
        "pending_evaluations": pending,
        "completed_evaluations": done,
        "latest_result": _latest_result(user),
    }
