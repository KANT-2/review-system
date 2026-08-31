import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import AIUsageLog, PostIt, PostItConnection, PRDProject, PRDQuestion, PRDSection
from .services import AICoachError, ask_ai_coach, generate_question_draft, get_chat_history

User = get_user_model()

TEMPLATE_TYPES = [
    {
        "id": "new-product",
        "label": "신규 프로젝트",
        "description": "새로운 서비스를 처음 만드는 경우. 누구의 어떤 문제를 해결하며, 최소한 무엇을 만들어 검증할지에 집중합니다.",
        "icon": "🚀",
        "color": "indigo",
        "variants": [
            {
                "id": "b2c-app",
                "label": "B2C 앱/서비스",
                "description": "개인 사용자를 타겟으로 하는 소비자 서비스",
                "example": "학습 앱, 건강 관리, 커머스, 구독 서비스 등",
            },
            {
                "id": "b2b-saas",
                "label": "B2B SaaS/플랫폼",
                "description": "기업 또는 팀을 고객으로 하는 비즈니스 소프트웨어",
                "example": "협업 툴, 분석 플랫폼, ERP/CRM, API 서비스 등",
            },
            {
                "id": "internal-tool",
                "label": "사내 도구/어드민",
                "description": "내부 업무 효율화를 위한 운영 도구",
                "example": "고객 관리 어드민, 데이터 파이프라인, 모니터링 대시보드 등",
            },
        ],
    },
    {
        "id": "new-feature",
        "label": "신규 기능",
        "description": "운영 중이거나 개발 중인 서비스에 새로운 기능을 추가할 때. 기존 서비스에서 충족하지 못한 니즈와 신규 기능의 연결 방식에 집중합니다.",
        "icon": "⚡",
        "color": "violet",
        "variants": [
            {
                "id": "core-feature",
                "label": "핵심 기능 추가",
                "description": "서비스 핵심 가치를 확장하는 새로운 기능",
                "example": "소셜 기능, 분석 리포트, 자동화 기능 등",
            },
            {
                "id": "integration",
                "label": "외부 서비스 연동",
                "description": "타 플랫폼·API와의 통합 기능",
                "example": "Slack 알림, 캘린더 연동, 결제 게이트웨이 추가 등",
            },
            {
                "id": "channel-expand",
                "label": "채널/기기 확장",
                "description": "새로운 접점이나 플랫폼으로 서비스 확장",
                "example": "모바일 앱, 웹 클리퍼, 위젯, 이메일 다이제스트 등",
            },
        ],
    },
    {
        "id": "improvement",
        "label": "기능 개선",
        "description": "이미 제공 중인 기능의 사용성·성능·정책·성과를 개선할 때. 현재 문제의 근거, 변경 전후 차이, 기존 사용자 영향에 집중합니다.",
        "icon": "🔧",
        "color": "emerald",
        "variants": [
            {
                "id": "ux-improvement",
                "label": "UX/사용성 개선",
                "description": "사용자 경험과 인터페이스 개선",
                "example": "업로드 플로우 개선, 온보딩 최적화, 에러 안내 강화 등",
            },
            {
                "id": "performance",
                "label": "성능/기술 개선",
                "description": "속도, 안정성, 확장성 향상",
                "example": "검색 속도 개선, 캐시 최적화, 마이그레이션 등",
            },
            {
                "id": "policy-change",
                "label": "정책/비즈니스 규칙 변경",
                "description": "운영 정책이나 비즈니스 로직 변경",
                "example": "결제 정책 변경, 권한 구조 개편, 약관 업데이트 등",
            },
        ],
    },
]

# 새 PRD 생성 시 채워 넣는 기본 섹션/문항 구성 (유형과 무관하게 공통으로 사용)
DEFAULT_SECTIONS = [
    {
        "title": "프로젝트 요약",
        "step": 1,
        "guidance": "서비스를 처음 접하는 사람도 이해할 수 있도록 3~5줄로 설명하세요.",
        "questions": [
            "프로젝트명은 무엇인가요?",
            "한 줄 소개를 작성해주세요.",
            "해결하려는 핵심 문제는 무엇인가요?",
            "최초 출시 범위는 어디까지인가요?",
        ],
    },
    {
        "title": "서비스 목표 및 핵심 가치",
        "step": 1,
        "guidance": "어떤 기능을 만들지보다, 사용자의 상황을 어떻게 바꿀지 작성하세요.",
        "questions": [
            "서비스 목표를 한 문장으로 정의해주세요.",
            "사용자가 얻는 핵심 가치는 무엇인가요?",
            "기존 대안 대비 차별점은?",
        ],
    },
    {
        "title": "추진 배경 및 기회",
        "step": 2,
        "guidance": "왜 이 문제가 존재하고, 왜 지금 해결할 가치가 있는지 설명하세요.",
        "questions": [
            "문제를 발견한 계기는 무엇인가요?",
            "시장 동향 및 기회를 설명하세요.",
            "경쟁사·기존 대안의 한계는 무엇인가요?",
        ],
    },
    {
        "title": "핵심 타겟 및 이용 상황",
        "step": 3,
        "guidance": "넓게 정의하지 마세요. 문제가 특히 자주 발생하는 첫 사용자군을 선정하세요.",
        "questions": [
            "최우선 타겟은 누구인가요?",
            "이 타겟을 먼저 선택한 이유는?",
            "대표 페르소나의 이용 상황을 구체적으로 설명하세요.",
        ],
    },
    {
        "title": "핵심 MVP 범위",
        "step": 4,
        "guidance": "서비스의 핵심 가치를 경험하는 데 필요한 최소 범위를 정하세요.",
        "questions": [
            "핵심 유저 플로우를 단계별로 작성해주세요.",
            "Must Have 기능 목록을 나열해주세요.",
            "Out of Scope로 명확히 제외할 기능은?",
        ],
    },
    {
        "title": "성공 지표 및 검증 계획",
        "step": 6,
        "guidance": "출시했다는 사실이 아니라, 사용자가 핵심 가치를 얻었는지 판단할 지표를 작성하세요.",
        "questions": [
            "핵심 정량 지표(KPI)는 무엇인가요?",
            "정성적 성공 기준은 무엇인가요?",
            "목표 달성 시 후속 방향은?",
        ],
    },
]

MEMBER_COLORS = ["#4F46E5", "#059669", "#D97706", "#7C3AED", "#DC2626", "#0891B2"]


def _member_color(user):
    return MEMBER_COLORS[user.pk % len(MEMBER_COLORS)]


def _serialize_member(m):
    return {
        "id": m.pk,
        "name": m.get_full_name() or m.first_name or m.email,
        "initials": (m.get_full_name() or m.email)[:2],
        "color": _member_color(m),
        "role": m.get_role_display() if hasattr(m, "get_role_display") else "",
    }


def _my_collaborator_groups(user):
    """이 유저와 이미 같은 PRD에 참여한 적 있는 동료들을 프로젝트 단위로 묶어서 반환한다.
    (원본 zip의 "내가 속한 팀" 빠른 추가 UI에 대응 - PRD 앱에는 별도 팀 개념이 없어 협업 이력으로 대체)"""
    projects = (
        PRDProject.objects.filter(members=user)
        .annotate(member_count=Count("members"))
        .filter(member_count__gt=1)
        .prefetch_related("members")
        .distinct()[:5]
    )
    groups = []
    for p in projects:
        member_ids = [m.pk for m in p.members.all() if m.pk != user.pk]
        if member_ids:
            groups.append({"name": p.title, "member_ids": member_ids})
    return groups


@login_required
def home(request):
    projects = (
        PRDProject.objects.filter(members=request.user)
        .distinct()
        .prefetch_related("sections__questions", "members")
    )

    total = projects.count()
    in_progress = projects.filter(status=PRDProject.Status.WRITING).count()
    completed = projects.filter(status=PRDProject.Status.DONE).count()
    scores = [p.completion_score for p in projects]
    avg_score = round(sum(scores) / len(scores)) if scores else 0
    ai_sessions = sum(p.ai_coaching_sessions for p in projects)

    today = timezone.localdate()
    soon_deadline = sum(1 for p in projects if p.deadline and 0 <= (p.deadline - today).days <= 7)

    weekly_activity = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = projects.filter(updated_at__date=day).count()
        weekly_activity.append(min(100, count * 25))

    recent_activities = [
        {
            "who": p.created_by.get_full_name() or p.created_by.first_name or "사용자",
            "project_title": p.title,
            "detail": "내용을 수정했습니다",
            "time": p.updated_at.strftime("%m/%d %H:%M"),
            "color": _member_color(p.created_by),
        }
        for p in projects.order_by("-updated_at")[:5]
    ]

    context = {
        "user_name": request.user.get_full_name() or request.user.first_name or "사용자",
        "stats": {
            "total": total,
            "in_progress": in_progress,
            "avg_score": avg_score,
            "completed": completed,
            "ai_sessions": ai_sessions,
            "soon_deadline": soon_deadline,
        },
        "prds": projects,
        "weekly_activity": weekly_activity,
        "recent_activities": recent_activities,
        "status_choices": PRDProject.Status.choices,
    }
    return render(request, "ideas/home.html", context)


@login_required
def prd_new(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        deadline = request.POST.get("deadline") or None
        if not title:
            return HttpResponseBadRequest("제목은 필수입니다.")
        if not deadline:
            return HttpResponseBadRequest("목표 마감일은 필수입니다.")
        project_type = request.POST.get("project_type") or PRDProject.ProjectType.NEW_PRODUCT
        description = request.POST.get("description", "").strip()
        author_ids = request.POST.getlist("author_ids")

        with transaction.atomic():
            project = PRDProject.objects.create(
                title=title,
                description=description,
                project_type=project_type,
                deadline=deadline,
                created_by=request.user,
            )
            project.members.add(request.user)
            valid_author_ids = User.objects.filter(pk__in=author_ids).values_list("pk", flat=True)
            project.members.add(*valid_author_ids)

            for order, section_data in enumerate(DEFAULT_SECTIONS):
                section = PRDSection.objects.create(
                    project=project,
                    title=section_data["title"],
                    guidance=section_data["guidance"],
                    step=section_data["step"],
                    order=order,
                )
                for q_order, question_text in enumerate(section_data["questions"]):
                    PRDQuestion.objects.create(
                        section=section, question=question_text, order=q_order
                    )

        return redirect("ideas:prd_write", pk=project.pk)

    other_members = User.objects.exclude(pk=request.user.pk).order_by("first_name")[:100]
    context = {
        "template_types": TEMPLATE_TYPES,
        "template_types_json": json.dumps(TEMPLATE_TYPES, ensure_ascii=False),
        "current_user_member": _serialize_member(request.user),
        "other_members_json": json.dumps(
            [_serialize_member(m) for m in other_members], ensure_ascii=False
        ),
        "collaborator_groups_json": json.dumps(
            _my_collaborator_groups(request.user), ensure_ascii=False
        ),
    }
    return render(request, "ideas/prd_new.html", context)


@login_required
def prd_write(request, pk):
    project = get_object_or_404(
        PRDProject.objects.prefetch_related("sections__questions", "members"),
        pk=pk,
        members=request.user,
    )

    sections = list(project.sections.all())
    sections_json = [
        {
            "id": str(section.id),
            "title": section.title,
            "questions": [
                {"id": str(q.id), "question": q.question, "answer": q.answer, "is_held": q.is_held}
                for q in section.questions.all()
            ],
        }
        for section in sections
    ]

    members = [{**_serialize_member(m), "contribution_pct": 0} for m in project.members.all()]

    context = {
        "project": project,
        "sections": [
            {
                "id": str(s.id),
                "title": s.title,
                "questions": [
                    {
                        "id": str(q.id),
                        "question": q.question,
                        "hint": q.guidance,
                        "answer": q.answer,
                        "is_held": q.is_held,
                    }
                    for q in s.questions.all()
                ],
            }
            for s in sections
        ],
        "sections_json": json.dumps(sections_json, ensure_ascii=False),
        "members": members,
        "completion_score": project.completion_score,
        "ai_coaching_sessions": project.ai_coaching_sessions,
        "status_choices": PRDProject.Status.choices,
    }
    return render(request, "ideas/prd_write.html", context)


@login_required
@require_POST
def prd_update_status(request, pk):
    project = get_object_or_404(PRDProject, pk=pk, members=request.user)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}
    status = payload.get("status")
    if status not in PRDProject.Status.values:
        return HttpResponseBadRequest("유효하지 않은 상태입니다.")
    project.status = status
    update_fields = ["status", "updated_at"]
    if "deadline" in payload:
        project.deadline = payload["deadline"] or None
        update_fields.append("deadline")
    project.save(update_fields=update_fields)
    return JsonResponse({"ok": True, "status": project.status})


@login_required
@require_POST
def prd_update_section_title(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest("invalid json")

    section_id = payload.get("section_id")
    title = (payload.get("title") or "").strip()
    if not title:
        return HttpResponseBadRequest("제목은 비어 있을 수 없습니다.")

    section = get_object_or_404(
        PRDSection.objects.filter(project__members=request.user), pk=section_id
    )
    section.title = title
    section.save(update_fields=["title"])
    section.project.save(update_fields=["updated_at"])
    return JsonResponse({"ok": True, "title": section.title})


@login_required
@require_POST
def prd_update_question_text(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest("invalid json")

    question_id = payload.get("question_id")
    text = (payload.get("question") or "").strip()
    if not text:
        return HttpResponseBadRequest("질문 내용은 비어 있을 수 없습니다.")

    question = get_object_or_404(
        PRDQuestion.objects.filter(section__project__members=request.user), pk=question_id
    )
    question.question = text
    question.save(update_fields=["question"])
    question.section.project.save(update_fields=["updated_at"])
    return JsonResponse({"ok": True, "question": question.question})


@login_required
@require_POST
def prd_save_answer(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest("invalid json")

    question_id = payload.get("question_id")
    question = get_object_or_404(
        PRDQuestion.objects.filter(section__project__members=request.user), pk=question_id
    )

    if "answer" in payload:
        question.answer = payload["answer"]
    if "is_held" in payload:
        question.is_held = bool(payload["is_held"])
    question.save(update_fields=["answer", "is_held"])
    question.section.project.save(update_fields=["updated_at"])

    return JsonResponse({"ok": True})


@login_required
def brainstorm(request, pk):
    project = get_object_or_404(PRDProject, pk=pk, members=request.user)

    postits = [
        {
            "id": str(p.id),
            "content": p.content,
            "color": p.color,
            "nodeType": p.node_type,
            "x": p.x,
            "y": p.y,
            "authorId": str(p.author_id),
            "assigneeId": str(p.assignee_id) if p.assignee_id else None,
            "status": p.status,
            "rotation": p.rotation,
        }
        for p in project.postits.all()
    ]
    connections = [
        {"id": str(c.id), "fromId": str(c.from_postit_id), "toId": str(c.to_postit_id)}
        for c in project.connections.all()
    ]
    members = [{**_serialize_member(m), "id": str(m.pk)} for m in project.members.all()]

    context = {
        "project": project,
        "initial_postits_json": json.dumps(postits, ensure_ascii=False),
        "initial_connections_json": json.dumps(connections, ensure_ascii=False),
        "members_json": json.dumps(members, ensure_ascii=False),
    }
    return render(request, "ideas/brainstorm.html", context)


@login_required
@require_POST
def brainstorm_sync(request, pk):
    project = get_object_or_404(PRDProject, pk=pk, members=request.user)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest("invalid json")

    postits = payload.get("postits", [])
    connections = payload.get("connections", [])

    with transaction.atomic():
        project.postits.all().delete()
        id_map = {}
        for p in postits:
            author_id = int(p["authorId"]) if p.get("authorId") else request.user.pk
            assignee_id = int(p["assigneeId"]) if p.get("assigneeId") else None
            obj = PostIt.objects.create(
                project=project,
                content=p.get("content", ""),
                color=p.get("color", "#FEF9C3"),
                node_type=p.get("nodeType", PostIt.NodeType.NOTE),
                x=p.get("x", 0),
                y=p.get("y", 0),
                rotation=p.get("rotation", 0),
                author_id=author_id,
                assignee_id=assignee_id,
                status=p.get("status", PostIt.Status.DEFAULT),
            )
            id_map[str(p["id"])] = obj.id

        for c in connections:
            from_id = id_map.get(str(c.get("fromId")))
            to_id = id_map.get(str(c.get("toId")))
            if from_id and to_id:
                PostItConnection.objects.get_or_create(
                    project=project, from_postit_id=from_id, to_postit_id=to_id
                )

        project.save(update_fields=["updated_at"])

    return JsonResponse({"ok": True})


@login_required
@require_POST
def ai_coach_ask(request, pk):
    project = get_object_or_404(
        PRDProject.objects.prefetch_related("sections__questions"), pk=pk, members=request.user
    )
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return HttpResponseBadRequest("invalid json")

    message = (payload.get("message") or "").strip()
    if not message:
        return HttpResponseBadRequest("메시지를 입력해주세요.")
    section_id = payload.get("section_id")
    section = get_object_or_404(project.sections, pk=section_id) if section_id else None

    try:
        reply = ask_ai_coach(project, section=section, user=request.user, message=message)
    except AICoachError:
        return JsonResponse(
            {
                "ok": False,
                "error": "AI Coach 응답을 가져오는 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.",
            },
            status=502,
        )

    project.ai_coaching_sessions += 1
    project.save(update_fields=["ai_coaching_sessions"])
    AIUsageLog.objects.create(
        user=request.user,
        prd=project,
        feature_type=AIUsageLog.FeatureType.COACHING,
        total_tokens=reply.total_tokens,
    )

    return JsonResponse({"ok": True, "reply": reply.text})


@login_required
@require_GET
def ai_coach_history(request, pk):
    """(project, section, 현재 유저) 조합으로 저장된 대화 전체를 그대로 돌려준다.

    프론트는 이 배열을 자르거나 가공하지 않고 그대로 화면에 복원한다.
    """
    project = get_object_or_404(PRDProject, pk=pk, members=request.user)
    section_id = request.GET.get("section_id")
    section = get_object_or_404(project.sections, pk=section_id) if section_id else None

    messages = get_chat_history(project, section=section, user=request.user)
    return JsonResponse({"ok": True, "messages": messages})


@login_required
@require_POST
def ai_coach_draft(request, pk):
    """섹션 안에서 아직 비어 있는 첫 질문에 대한 AI 초안을 생성해 돌려준다.

    이 초안은 저장되지 않는다 — 사용자가 화면에서 검토/수정 후 "PRD에 반영하기"를
    눌러야 기존 prd_save_answer 엔드포인트를 통해 실제로 저장된다.
    """
    project = get_object_or_404(
        PRDProject.objects.prefetch_related("sections__questions"), pk=pk, members=request.user
    )
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return HttpResponseBadRequest("invalid json")

    section_id = payload.get("section_id")
    section = get_object_or_404(project.sections, pk=section_id)

    target_question = next(
        (q for q in section.questions.all() if not q.is_held and not q.answer.strip()), None
    )
    if target_question is None:
        return JsonResponse(
            {"ok": False, "error": "이 섹션에는 초안을 만들 빈 질문이 없습니다."}, status=400
        )

    try:
        reply = generate_question_draft(project, section=section, question=target_question)
    except AICoachError:
        return JsonResponse(
            {
                "ok": False,
                "error": "AI Coach 응답을 가져오는 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.",
            },
            status=502,
        )

    project.ai_coaching_sessions += 1
    project.save(update_fields=["ai_coaching_sessions"])
    AIUsageLog.objects.create(
        user=request.user,
        prd=project,
        feature_type=AIUsageLog.FeatureType.GENERATE,
        total_tokens=reply.total_tokens,
    )

    return JsonResponse(
        {
            "ok": True,
            "draft": reply.text,
            "question_id": str(target_question.id),
            "question_text": target_question.question,
        }
    )
