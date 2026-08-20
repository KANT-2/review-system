import os
from datetime import timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from allauth.account.models import EmailAddress  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import User, WhitelistEmail  # noqa: E402
from results.application import calculate_round, toggle_publication  # noqa: E402
from results.models import CalculationRun  # noqa: E402
from reviews.models import ReviewAnswer, ReviewSubmission  # noqa: E402
from rounds.models import (  # noqa: E402
    EvaluationRound,
    QuestionTemplate,
    RoundParticipant,
    TemplateQuestion,
)
from teams.models import Team, TeamMembership  # noqa: E402

DEV_PASSWORD = "Local-Only-Strong-Password-2026!"


def ensure_user(
    *,
    email,
    name,
    role,
    approval_status,
    phone_number="",
    student_number="",
):
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(
            email=email,
            password=DEV_PASSWORD,
            _email_verified=True,
            first_name=name,
            role=role,
            approval_status=approval_status,
            phone_number=phone_number,
            student_number=student_number or None,
            is_onboarded=approval_status == User.ApprovalStatus.APPROVED,
        )
    else:
        user.first_name = name
        user.role = role
        user.approval_status = approval_status
        user.phone_number = phone_number
        if student_number:
            user.student_number = student_number
        user.is_staff = role == User.Role.ADMIN
        user.set_password(DEV_PASSWORD)
        user.save()
        EmailAddress.objects.filter(user=user, primary=True).update(verified=True)
    return user


def ensure_template(*, tutor, name, category, prompts):
    template, _ = QuestionTemplate.objects.get_or_create(
        name=name,
        category=category,
        defaults={
            "description": "로컬 화면 확인용 기본 질문지",
            "created_by": tutor,
        },
    )
    if not template.is_locked:
        for order, prompt in enumerate(prompts, start=1):
            TemplateQuestion.objects.get_or_create(
                template=template,
                display_order=order,
                defaults={
                    "prompt": prompt,
                    "response_type": TemplateQuestion.ResponseType.RATING_5,
                },
            )
    return template


def ensure_round(*, title, tutor, students, team_template, peer_template, status, weeks_ago=1):
    """weeks_ago는 완료된 회차의 완료일을 서로 다르게 벌려서, 점수 추이 그래프의 회차 순서가
    뒤섞이지 않게 한다(완료일이 같으면 정렬 순서가 안정적이지 않다)."""
    now = timezone.now()
    completed = status == EvaluationRound.Status.COMPLETED
    in_progress = status == EvaluationRound.Status.IN_PROGRESS
    completed_at = now - timedelta(weeks=weeks_ago)
    defaults = {
        "description": "실제 ORM 흐름을 확인하기 위한 로컬 개발 회차입니다.",
        "evaluation_start_at": (
            completed_at - timedelta(days=7)
            if completed
            else now - timedelta(days=1)
            if in_progress
            else now + timedelta(days=8)
        ),
        "evaluation_end_at": (
            completed_at if completed else now + timedelta(days=7 if in_progress else 15)
        ),
        "target_team_count": 2,
        "team_template": team_template,
        "peer_template": peer_template,
        "created_by": tutor,
        "status": status,
        "started_at": (
            completed_at - timedelta(days=7)
            if completed
            else now - timedelta(days=1)
            if in_progress
            else None
        ),
        "completed_at": completed_at if completed else None,
    }
    round_obj, _ = EvaluationRound.objects.get_or_create(title=title, defaults=defaults)
    participants = []
    for student in students:
        participant, _ = RoundParticipant.objects.get_or_create(
            round=round_obj,
            user=student,
            defaults={
                "student_number_snapshot": student.student_number,
                "display_name_snapshot": student.first_name,
            },
        )
        participants.append(participant)
    teams = []
    midpoint = len(participants) // 2
    for number, members in enumerate((participants[:midpoint], participants[midpoint:]), start=1):
        team, _ = Team.objects.get_or_create(
            round=round_obj,
            team_number=number,
            defaults={"name": f"{number}팀"},
        )
        teams.append(team)
        for participant in members:
            TeamMembership.objects.get_or_create(team=team, participant=participant)
    return round_obj, participants, teams


def ensure_rating_submission(*, round_obj, evaluator, review_type, target, question, rating):
    target_field = (
        {"target_team": target}
        if review_type == ReviewSubmission.ReviewType.TEAM
        else {"target_participant": target}
    )
    submission, _ = ReviewSubmission.objects.get_or_create(
        round=round_obj,
        evaluator=evaluator,
        review_type=review_type,
        **target_field,
    )
    ReviewAnswer.objects.get_or_create(
        submission=submission,
        question=question,
        defaults={"rating_value": rating},
    )


def ensure_review_data(
    *, round_obj, participants, teams, team_question, peer_question, complete, rating_base=4
):
    """rating_base(3~4)를 회차마다 다르게 주면 점수 추이 그래프가 오르내리는 모습을 볼 수 있다."""
    team_size = len(participants) // 2
    team_limit = len(participants) if complete else 2
    for index, evaluator in enumerate(participants[:team_limit]):
        own_team_index = 0 if index < team_size else 1
        ensure_rating_submission(
            round_obj=round_obj,
            evaluator=evaluator,
            review_type=ReviewSubmission.ReviewType.TEAM,
            target=teams[1 - own_team_index],
            question=team_question,
            rating=min(rating_base + (index % 2), 5),
        )
    peer_pairs = []
    for members in (participants[:team_size], participants[team_size:]):
        peer_pairs.extend(
            (evaluator, target)
            for evaluator in members
            for target in members
            if evaluator != target
        )
    if not complete:
        peer_pairs = peer_pairs[:2]
    for index, (evaluator, target) in enumerate(peer_pairs):
        ensure_rating_submission(
            round_obj=round_obj,
            evaluator=evaluator,
            review_type=ReviewSubmission.ReviewType.PEER,
            target=target,
            question=peer_question,
            rating=min(rating_base + (index % 2), 5),
        )


def seed():
    print("Creating student whitelist entries...")
    for email in ("student1@ax.com", "student2@ax.com", "student3@ax.com"):
        WhitelistEmail.objects.get_or_create(email=email)

    tutor = ensure_user(
        email="tutor@ax.com",
        name="박교수",
        role=User.Role.TUTOR,
        approval_status=User.ApprovalStatus.APPROVED,
    )
    students = [
        ensure_user(
            email="student@ax.com",
            name="김민준",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            phone_number="010-1234-5678",
            student_number="AX202601",
        )
    ]
    for index, (name, email) in enumerate(
        (
            ("이수진", "sujin.lee@ax.com"),
            ("박도현", "dohyun.park@ax.com"),
            ("최민아", "mina.choi@ax.com"),
            ("강태호", "taeho.kang@ax.com"),
            ("윤서준", "seojun.yoon@ax.com"),
        ),
        start=2,
    ):
        students.append(
            ensure_user(
                email=email,
                name=name,
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
                student_number=f"AX2026{index:02d}",
            )
        )
    students.append(
        ensure_user(
            email="test-student@ax.com",
            name="테스트학생",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            student_number="AX202607",
        )
    )
    for name, email in (
        ("정우성", "woosung.jung@example.com"),
        ("한지민", "jimin.han@example.com"),
    ):
        ensure_user(
            email=email,
            name=name,
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.PENDING,
        )

    team_template = ensure_template(
        tutor=tutor,
        name="기본 팀 평가",
        category=QuestionTemplate.Category.TEAM,
        prompts=("결과물의 완성도는 충분한가요?", "발표 내용이 명확했나요?"),
    )
    peer_template = ensure_template(
        tutor=tutor,
        name="기본 개인 평가",
        category=QuestionTemplate.Category.PEER,
        prompts=("팀 과제에 적극적으로 기여했나요?", "협업과 소통이 원활했나요?"),
    )
    team_question = team_template.questions.first()
    peer_question = peer_template.questions.first()

    # 1~5회차를 완료·채점·전체 공개까지 끝내 둔다 - 마이페이지 점수 추이 그래프를 보려면
    # 완료된 회차가 여러 개 있어야 한다. rating_base를 회차마다 다르게 줘서 그래프가
    # 오르내리는 모습을 볼 수 있게 한다.
    for round_number, rating_base in ((1, 4), (2, 3), (3, 4), (4, 3), (5, 4)):
        completed_round, completed_participants, completed_teams = ensure_round(
            title=f"4기 프로젝트 평가 {round_number}회차",
            tutor=tutor,
            students=students,
            team_template=team_template,
            peer_template=peer_template,
            status=EvaluationRound.Status.COMPLETED,
            weeks_ago=(6 - round_number),
        )
        ensure_review_data(
            round_obj=completed_round,
            participants=completed_participants,
            teams=completed_teams,
            team_question=team_question,
            peer_question=peer_question,
            complete=True,
            rating_base=rating_base,
        )
        if not CalculationRun.objects.filter(round=completed_round, is_active=True).exists():
            calculate_round(round_id=completed_round.pk, actor=tutor)
        active_run = CalculationRun.objects.get(round=completed_round, is_active=True)
        for item_key, field_name in (
            ("team_winner", "winner_published_at"),
            ("team_ranking", "team_ranking_published_at"),
            ("my_score", "my_score_published_at"),
            ("peer_ranking", "peer_ranking_published_at"),
        ):
            if getattr(active_run, field_name) is None:
                toggle_publication(
                    round_id=completed_round.pk,
                    item_key=item_key,
                    actor=tutor,
                )
                active_run.refresh_from_db()

    active_round, active_participants, active_teams = ensure_round(
        title="4기 프로젝트 평가 6회차",
        tutor=tutor,
        students=students,
        team_template=team_template,
        peer_template=peer_template,
        status=EvaluationRound.Status.IN_PROGRESS,
    )
    ensure_review_data(
        round_obj=active_round,
        participants=active_participants,
        teams=active_teams,
        team_question=team_question,
        peer_question=peer_question,
        complete=False,
    )

    ensure_round(
        title="4기 프로젝트 평가 7회차",
        tutor=tutor,
        students=students,
        team_template=team_template,
        peer_template=peer_template,
        status=EvaluationRound.Status.DRAFT,
    )

    print("Development users, rounds, teams, reviews, and published results created.")
    print("Password for seeded users:", DEV_PASSWORD)


if __name__ == "__main__":
    seed()
