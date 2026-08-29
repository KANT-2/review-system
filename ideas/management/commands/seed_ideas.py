from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from ideas.models import PostIt, PostItConnection, PRDProject, PRDQuestion, PRDSection
from ideas.views import DEFAULT_SECTIONS

User = get_user_model()

SAMPLE_PROJECTS = [
    {
        "title": "AI 기반 PRD 작성 도구",
        "description": "초기 제품 아이디어를 구체적인 PRD로 발전시키는 AI 협업 도구",
        "project_type": PRDProject.ProjectType.NEW_PRODUCT,
        "status": PRDProject.Status.WRITING,
        "deadline_days": 13,
        "ai_coaching_sessions": 8,
    },
    {
        "title": "알림 커스터마이징 기능",
        "description": "사용자가 알림 빈도·종류·채널을 직접 설정하는 개인화 알림",
        "project_type": PRDProject.ProjectType.NEW_FEATURE,
        "status": PRDProject.Status.DONE,
        "deadline_days": -12,
        "ai_coaching_sessions": 6,
    },
    {
        "title": "검색 성능 최적화",
        "description": "검색 응답 속도 개선 및 결과 정확도 향상을 위한 기술 개선",
        "project_type": PRDProject.ProjectType.IMPROVEMENT,
        "status": PRDProject.Status.WRITING,
        "deadline_days": 18,
        "ai_coaching_sessions": 2,
    },
]

SAMPLE_POSTITS = [
    {
        "content": "AI가 대신 써주는 것보다 사용자가 생각하도록 돕는 게 핵심",
        "color": "#FEF9C3",
        "x": 80,
        "y": 100,
        "status": "accepted",
        "rotation": -1.5,
    },
    {
        "content": "PM뿐 아니라 개발자·디자이너도 PRD 작성에 참여",
        "color": "#DBEAFE",
        "x": 320,
        "y": 80,
        "status": "accepted",
        "rotation": 1.2,
    },
    {
        "content": "브레인스토밍 → PRD 반영률로 팀원 기여도 자동 평가",
        "color": "#EDE9FE",
        "x": 560,
        "y": 120,
        "status": "accepted",
        "rotation": -0.8,
    },
    {
        "content": "보류함: 확정 전 아이디어를 맥락과 함께 보존",
        "color": "#D1FAE5",
        "x": 800,
        "y": 90,
        "status": "default",
        "rotation": 1.8,
    },
]


class Command(BaseCommand):
    help = "아이디어 디벨로퍼(ideas 앱) 데모용 샘플 PRD 데이터를 만든다."

    @transaction.atomic
    def handle(self, *args, **options):
        users = list(User.objects.order_by("id")[:5])
        if not users:
            self.stderr.write("사용자가 없습니다. 먼저 seed_data.py를 실행해주세요.")
            return

        owner = users[0]
        today = date.today()

        for spec in SAMPLE_PROJECTS:
            if PRDProject.objects.filter(title=spec["title"]).exists():
                continue

            project = PRDProject.objects.create(
                title=spec["title"],
                description=spec["description"],
                project_type=spec["project_type"],
                status=spec["status"],
                deadline=today + timedelta(days=spec["deadline_days"]),
                ai_coaching_sessions=spec["ai_coaching_sessions"],
                created_by=owner,
            )
            project.members.set(users[:3])

            for order, section_data in enumerate(DEFAULT_SECTIONS):
                section = PRDSection.objects.create(
                    project=project,
                    title=section_data["title"],
                    guidance=section_data["guidance"],
                    step=section_data["step"],
                    order=order,
                )
                for q_order, question_text in enumerate(section_data["questions"]):
                    answer = ""
                    if project.status == PRDProject.Status.DONE or (order == 0 and q_order < 2):
                        answer = f"{question_text} (샘플 답변)"
                    PRDQuestion.objects.create(
                        section=section, question=question_text, answer=answer, order=q_order
                    )

            if spec is SAMPLE_PROJECTS[0]:
                for postit in SAMPLE_POSTITS:
                    PostIt.objects.create(project=project, author=owner, **postit)
                postits = list(project.postits.all())
                if len(postits) >= 2:
                    PostItConnection.objects.create(
                        project=project, from_postit=postits[0], to_postit=postits[1]
                    )

            self.stdout.write(self.style.SUCCESS(f"생성됨: {project.title}"))

        self.stdout.write(self.style.SUCCESS("완료"))
