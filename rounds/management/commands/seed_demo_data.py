"""이미 운영 중인 DB에 회차·팀·질문지·평가 응답 시드 데이터를 채운다.

사용자 계정은 만들지도 고치지도 않는다 - 이미 승인된 수강생을 참가자로 끌어다 쓴다.
채점(CalculationRun)·결과 공개·메일 발송도 건드리지 않아서, 이 명령만으로는 수강생
화면에 결과가 새로 공개되거나 메일이 나가는 일이 없다.

회차 제목에 --title-prefix(기본 "[시드]")가 그대로 붙는다. 재실행하면 같은 제목의
회차를 다시 찾아 쓰기 때문에 중복이 쌓이지 않고, 나중에 정리할 때도 이 접두어로
시드 데이터만 골라낼 수 있다.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from reviews.models import ReviewAnswer, ReviewFinalSubmission, ReviewSubmission
from rounds.models import (
    EvaluationRound,
    QuestionTemplate,
    RoundParticipant,
    TemplateQuestion,
)
from rounds.services import participant_snapshot_values
from teams.models import Team, TeamMembership

RATING = TemplateQuestion.ResponseType.RATING_5
TEXT = TemplateQuestion.ResponseType.TEXT
Competency = TemplateQuestion.Competency

TEAM_QUESTIONS = (
    (RATING, "결과물의 완성도가 충분한가요?", Competency.PROBLEM_SOLVING),
    (RATING, "발표 내용이 명확하게 전달되었나요?", Competency.COMMUNICATION),
    (RATING, "기술적 구현 수준이 요구사항에 맞았나요?", Competency.DEV_UNDERSTANDING),
    (RATING, "팀으로서 협업이 잘 이루어진 것으로 보였나요?", Competency.TEAMWORK),
    (TEXT, "이 팀의 강점과 개선점을 자유롭게 적어 주세요.", ""),
)

PEER_QUESTIONS = (
    (RATING, "팀 과제에 적극적으로 기여했나요?", Competency.RESPONSIBILITY),
    (RATING, "협업과 소통이 원활했나요?", Competency.COMMUNICATION),
    (RATING, "맡은 역할을 끝까지 책임졌나요?", Competency.TEAMWORK),
    (RATING, "문제 상황에서 해결 방향을 제시했나요?", Competency.PROBLEM_SOLVING),
    (RATING, "구현 내용을 팀에 이해시킬 만큼 알고 있었나요?", Competency.DEV_UNDERSTANDING),
    (TEXT, "함께 일하며 좋았던 점과 아쉬웠던 점을 적어 주세요.", ""),
)

TEAM_COMMENTS = (
    "요구사항을 빠짐없이 구현했고 발표 흐름도 깔끔했습니다.",
    "기능은 잘 동작했지만 예외 처리에 대한 설명이 조금 부족했습니다.",
    "역할 분담이 분명해서 결과물의 완성도가 높았습니다.",
    "아이디어가 좋았고, 다음에는 테스트 범위를 더 넓히면 좋겠습니다.",
)

PEER_COMMENTS = (
    "맡은 부분을 기한 안에 마무리해 주어 팀 일정이 밀리지 않았습니다.",
    "막힌 부분을 먼저 공유해 주어 함께 해결하기 수월했습니다.",
    "코드 리뷰 의견을 성실하게 반영해 주었습니다.",
    "회의에서 의견을 더 적극적으로 내주면 좋겠습니다.",
)


class _DryRunRollback(Exception):
    """--dry-run일 때 트랜잭션을 되돌리려고 일부러 던지는 예외."""


class Command(BaseCommand):
    help = "운영 DB에 회차·팀·질문지·평가 응답 시드 데이터를 채운다(사용자는 건드리지 않음)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--completed",
            type=int,
            default=3,
            help="만들 완료 회차 수 (기본 3). 회차마다 1주씩 과거로 벌린다.",
        )
        parser.add_argument(
            "--team-size",
            type=int,
            default=4,
            help="한 팀에 넣을 인원 수 (기본 4). 팀은 최소 2개가 되도록 조정한다.",
        )
        parser.add_argument(
            "--title-prefix",
            default="[시드]",
            help='회차 제목 접두어 (기본 "[시드]"). 시드 데이터를 구분·정리하는 표식이다.',
        )
        parser.add_argument(
            "--no-in-progress",
            action="store_true",
            help="진행 중 회차를 만들지 않는다.",
        )
        parser.add_argument(
            "--no-draft",
            action="store_true",
            help="준비 중 회차를 만들지 않는다.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="무엇이 만들어질지만 출력하고 끝에서 전부 롤백한다.",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.prefix = options["title_prefix"].strip()
        self.created = {}

        if options["completed"] < 0:
            raise CommandError("--completed는 0 이상이어야 합니다.")
        if options["team_size"] < 2:
            raise CommandError("--team-size는 2 이상이어야 합니다.")

        try:
            with transaction.atomic():
                self._seed(options)
                if self.dry_run:
                    raise _DryRunRollback
        except _DryRunRollback:
            self._report()
            self.stdout.write(
                self.style.WARNING("\n--dry-run이라 모두 롤백했습니다. DB는 그대로입니다.")
            )
            return

        self._report()
        self.stdout.write(self.style.SUCCESS("\n시드 데이터를 반영했습니다."))

    # 실제 작업 --------------------------------------------------------------

    def _seed(self, options):
        actor = self._resolve_actor()
        students = self._resolve_students()
        self.stdout.write(
            f"작성자: {actor.email} ({actor.get_role_display()}) / "
            f"참가자로 쓸 승인된 수강생: {len(students)}명"
        )

        team_template = self._ensure_template(
            actor=actor,
            name=self._titled("팀 평가 질문지"),
            category=QuestionTemplate.Category.TEAM,
            questions=TEAM_QUESTIONS,
        )
        peer_template = self._ensure_template(
            actor=actor,
            name=self._titled("개인 평가 질문지"),
            category=QuestionTemplate.Category.PEER,
            questions=PEER_QUESTIONS,
        )

        completed_count = options["completed"]
        team_size = options["team_size"]

        # 완료 회차부터 만든다. 완료일을 1주씩 벌려 놓아야 마이페이지 점수 추이가
        # 회차 순서대로 그려진다.
        for offset in range(completed_count):
            number = offset + 1
            weeks_ago = completed_count - offset
            round_obj, participants, teams = self._ensure_round(
                title=self._titled(f"평가 {number}회차"),
                actor=actor,
                students=students,
                team_template=team_template,
                peer_template=peer_template,
                team_size=team_size,
                status=EvaluationRound.Status.COMPLETED,
                weeks_ago=weeks_ago,
            )
            self._ensure_reviews(
                round_obj=round_obj,
                participants=participants,
                teams=teams,
                team_template=team_template,
                peer_template=peer_template,
                coverage=1.0,
                seed=number,
                finalize=True,
            )

        if not options["no_in_progress"]:
            self._ensure_in_progress_round(
                actor=actor,
                students=students,
                team_template=team_template,
                peer_template=peer_template,
                team_size=team_size,
                number=completed_count + 1,
            )

        if not options["no_draft"]:
            self._ensure_round(
                title=self._titled(f"평가 {completed_count + 2}회차"),
                actor=actor,
                students=students,
                team_template=team_template,
                peer_template=peer_template,
                team_size=team_size,
                status=EvaluationRound.Status.DRAFT,
            )

    def _ensure_in_progress_round(
        self, *, actor, students, team_template, peer_template, team_size, number
    ):
        """진행 중 회차는 DB 전체에 하나만 존재할 수 있다(rounds_single_in_progress).

        이미 진행 중인 회차가 있으면 운영 중인 실제 회차일 가능성이 높으므로 건드리지 않고
        건너뛴다.
        """
        title = self._titled(f"평가 {number}회차")
        existing = EvaluationRound.objects.filter(status=EvaluationRound.Status.IN_PROGRESS).first()
        if existing and existing.title != title:
            self.stdout.write(
                self.style.WARNING(
                    f"  진행 중 회차 건너뜀 - 이미 진행 중인 회차가 있습니다: {existing.title}"
                )
            )
            return
        round_obj, participants, teams = self._ensure_round(
            title=title,
            actor=actor,
            students=students,
            team_template=team_template,
            peer_template=peer_template,
            team_size=team_size,
            status=EvaluationRound.Status.IN_PROGRESS,
        )
        # 진행 중 회차는 일부만 제출한 상태로 둬서 미제출 현황 화면을 확인할 수 있게 한다.
        self._ensure_reviews(
            round_obj=round_obj,
            participants=participants,
            teams=teams,
            team_template=team_template,
            peer_template=peer_template,
            coverage=0.5,
            seed=number,
            finalize=False,
        )

    # 대상 사용자 ------------------------------------------------------------

    def _resolve_actor(self):
        actor = (
            User.objects.filter(
                role__in=(User.Role.ADMIN, User.Role.TUTOR),
                approval_status=User.ApprovalStatus.APPROVED,
                is_active=True,
            )
            .order_by("role", "pk")  # admin이 tutor보다 먼저 온다.
            .first()
        )
        if actor is None:
            raise CommandError(
                "승인된 관리자/튜터 계정이 없습니다. 회차 작성자로 쓸 계정이 필요합니다."
            )
        return actor

    def _resolve_students(self):
        students = list(
            User.objects.filter(
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
                is_active=True,
            ).order_by("pk")
        )
        if len(students) < 4:
            raise CommandError(
                f"승인된 수강생이 {len(students)}명뿐입니다. "
                "팀을 2개 이상 만들려면 최소 4명이 필요합니다."
            )
        return students

    # 질문지 ------------------------------------------------------------------

    def _ensure_template(self, *, actor, name, category, questions):
        template, created = QuestionTemplate.objects.get_or_create(
            name=name,
            category=category,
            defaults={
                "description": "시드 데이터로 만든 기본 질문지입니다.",
                "created_by": actor,
            },
        )
        self._count("질문지", created)
        if template.is_locked:
            # 이미 시작된 회차가 쓰고 있으면 문항을 건드릴 수 없다(모델 clean에서 막는다).
            self.stdout.write(f"  질문지 '{name}'은(는) 잠겨 있어 문항을 그대로 씁니다.")
            return template
        for order, (response_type, prompt, competency) in enumerate(questions, start=1):
            _, question_created = TemplateQuestion.objects.get_or_create(
                template=template,
                display_order=order,
                defaults={
                    "prompt": prompt,
                    "response_type": response_type,
                    "competency": competency,
                },
            )
            self._count("문항", question_created)
        return template

    # 회차·참가자·팀 ---------------------------------------------------------

    def _ensure_round(
        self,
        *,
        title,
        actor,
        students,
        team_template,
        peer_template,
        team_size,
        status,
        weeks_ago=0,
    ):
        now = timezone.now()
        completed = status == EvaluationRound.Status.COMPLETED
        in_progress = status == EvaluationRound.Status.IN_PROGRESS
        completed_at = now - timedelta(weeks=weeks_ago)
        team_count = max(2, -(-len(students) // team_size))

        if completed:
            start_at, end_at = completed_at - timedelta(days=7), completed_at
        elif in_progress:
            start_at, end_at = now - timedelta(days=1), now + timedelta(days=6)
        else:
            start_at, end_at = now + timedelta(days=8), now + timedelta(days=15)

        round_obj, created = EvaluationRound.objects.get_or_create(
            title=title,
            defaults={
                "description": "시드 데이터로 만든 회차입니다.",
                "evaluation_start_at": start_at,
                "evaluation_end_at": end_at,
                "target_team_count": team_count,
                "team_template": team_template,
                "peer_template": peer_template,
                "created_by": actor,
                "status": status,
                "started_at": start_at if (completed or in_progress) else None,
                "completed_at": completed_at if completed else None,
            },
        )
        self._count("회차", created)
        self.stdout.write(
            f"  회차 {'생성' if created else '재사용'}: {title} ({round_obj.get_status_display()})"
        )

        participants = []
        for student in students:
            participant, participant_created = RoundParticipant.objects.get_or_create(
                round=round_obj,
                user=student,
                defaults=participant_snapshot_values(student),
            )
            self._count("참가자", participant_created)
            participants.append(participant)

        teams = []
        chunk = -(-len(participants) // team_count)
        for number in range(1, team_count + 1):
            members = participants[(number - 1) * chunk : number * chunk]
            team, team_created = Team.objects.get_or_create(
                round=round_obj,
                team_number=number,
                defaults={"name": f"{number}팀"},
            )
            self._count("팀", team_created)
            teams.append((team, members))
            for participant in members:
                # participant는 팀에 OneToOne이라 이미 배정돼 있으면 그대로 둔다.
                _, membership_created = TeamMembership.objects.get_or_create(
                    participant=participant,
                    defaults={"team": team},
                )
                self._count("팀 배정", membership_created)
        return round_obj, participants, teams

    # 평가 응답 ---------------------------------------------------------------

    def _ensure_reviews(
        self,
        *,
        round_obj,
        participants,
        teams,
        team_template,
        peer_template,
        coverage,
        seed,
        finalize,
    ):
        team_questions = list(team_template.questions.all())
        peer_questions = list(peer_template.questions.all())
        team_of = {participant.pk: team for team, members in teams for participant in members}
        limit = max(1, int(len(participants) * coverage))
        evaluators = participants[:limit]

        for index, evaluator in enumerate(evaluators):
            own_team = team_of.get(evaluator.pk)
            # 팀 평가: 자기 팀을 뺀 나머지 팀 전부를 평가한다.
            for team, _members in teams:
                if own_team is not None and team.pk == own_team.pk:
                    continue
                self._ensure_submission(
                    round_obj=round_obj,
                    evaluator=evaluator,
                    review_type=ReviewSubmission.ReviewType.TEAM,
                    target={"target_team": team},
                    questions=team_questions,
                    comments=TEAM_COMMENTS,
                    seed=seed + index + team.team_number,
                )

        # 개인 평가: 같은 팀 안에서 자기 자신을 뺀 나머지를 평가한다.
        evaluator_pks = {participant.pk for participant in evaluators}
        for _team, members in teams:
            for index, evaluator in enumerate(members):
                if evaluator.pk not in evaluator_pks:
                    continue
                for offset, target in enumerate(members):
                    if target.pk == evaluator.pk:
                        continue
                    self._ensure_submission(
                        round_obj=round_obj,
                        evaluator=evaluator,
                        review_type=ReviewSubmission.ReviewType.PEER,
                        target={"target_participant": target},
                        questions=peer_questions,
                        comments=PEER_COMMENTS,
                        seed=seed + index + offset,
                    )

        if finalize:
            for evaluator in evaluators:
                for review_type in ReviewSubmission.ReviewType.values:
                    _, created = ReviewFinalSubmission.objects.get_or_create(
                        round=round_obj,
                        evaluator=evaluator,
                        review_type=review_type,
                    )
                    self._count("최종 제출", created)

    def _ensure_submission(
        self, *, round_obj, evaluator, review_type, target, questions, comments, seed
    ):
        submission, created = ReviewSubmission.objects.get_or_create(
            round=round_obj,
            evaluator=evaluator,
            review_type=review_type,
            **target,
        )
        self._count("평가 제출", created)
        for order, question in enumerate(questions):
            if question.response_type == TemplateQuestion.ResponseType.TEXT:
                values = {
                    "rating_value": None,
                    "text_value": comments[(seed + order) % len(comments)],
                }
            else:
                # 3~5점 사이에서 문항·평가자별로 조금씩 흔들어 준다.
                values = {
                    "rating_value": 3 + ((seed + order) % 3),
                    "text_value": "",
                }
            _, answer_created = ReviewAnswer.objects.get_or_create(
                submission=submission,
                question=question,
                defaults=values,
            )
            self._count("평가 응답", answer_created)

    # 출력 --------------------------------------------------------------------

    def _titled(self, text):
        return f"{self.prefix} {text}".strip()

    def _count(self, label, created):
        if created:
            self.created[label] = self.created.get(label, 0) + 1

    def _report(self):
        self.stdout.write("\n생성 요약")
        if not self.created:
            self.stdout.write("  새로 만든 항목이 없습니다(이미 모두 있는 상태).")
            return
        for label, count in self.created.items():
            self.stdout.write(f"  {label}: {count}건")
