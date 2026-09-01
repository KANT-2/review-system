from django.conf import settings
from django.db import models
from django.utils import timezone


class PRDProject(models.Model):
    class ProjectType(models.TextChoices):
        NEW_PRODUCT = "new-product", "신규 프로젝트"
        NEW_FEATURE = "new-feature", "신규 기능"
        IMPROVEMENT = "improvement", "개선"

    class Status(models.TextChoices):
        WRITING = "작성 중", "작성 중"
        DONE = "완료", "완료"
        HOLD = "홀딩", "홀딩"
        DROP = "드랍", "드랍"

    title = models.CharField(max_length=200)
    description = models.CharField(max_length=300, blank=True, default="")
    project_type = models.CharField(max_length=20, choices=ProjectType.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WRITING)
    deadline = models.DateField(null=True, blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="prd_projects", blank=True
    )
    ai_coaching_sessions = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_prd_projects"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return self.title

    @property
    def completion_score(self):
        sections = list(self.sections.all())
        if not sections:
            return 0
        return round(sum(s.completion_score for s in sections) / len(sections))

    @property
    def days_left(self):
        if not self.deadline:
            return None
        return (self.deadline - timezone.localdate()).days


class PRDSection(models.Model):
    project = models.ForeignKey(PRDProject, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=100)
    guidance = models.TextField(blank=True, default="")
    step = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return f"{self.project.title} - {self.title}"

    @property
    def completion_score(self):
        active = [q for q in self.questions.all() if not q.is_held]
        if not active:
            return 0
        answered = sum(1 for q in active if len(q.answer.strip()) > 5)
        return round(answered / len(active) * 100)


class PRDQuestion(models.Model):
    section = models.ForeignKey(PRDSection, on_delete=models.CASCADE, related_name="questions")
    question = models.CharField(max_length=300)
    guidance = models.CharField(max_length=300, blank=True, default="")
    answer = models.TextField(blank=True, default="")
    is_held = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return self.question


class PostIt(models.Model):
    class Status(models.TextChoices):
        DEFAULT = "default", "기본"
        ACCEPTED = "accepted", "채택됨"
        HELD = "held", "보류"

    class NodeType(models.TextChoices):
        NOTE = "note", "메모"
        TITLE = "title", "제목"

    project = models.ForeignKey(PRDProject, on_delete=models.CASCADE, related_name="postits")
    content = models.TextField()
    color = models.CharField(max_length=7, default="#FEF9C3")
    node_type = models.CharField(max_length=5, choices=NodeType.choices, default=NodeType.NOTE)
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    rotation = models.FloatField(default=0)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_postits"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_postits",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DEFAULT)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.content[:30]


class PostItConnection(models.Model):
    project = models.ForeignKey(PRDProject, on_delete=models.CASCADE, related_name="connections")
    from_postit = models.ForeignKey(PostIt, on_delete=models.CASCADE, related_name="+")
    to_postit = models.ForeignKey(PostIt, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project", "from_postit", "to_postit"), name="ideas_connection_unique"
            )
        ]

    def __str__(self):
        return f"{self.from_postit_id} -> {self.to_postit_id}"


class AIPrompt(models.Model):
    """팀 공통 ERD의 AI_Prompts 테이블. AI Coach/채팅 기능이 쓰는 system_instruction을
    코드가 아니라 DB에서 관리해서, 다른 기능(채팅 등)과 프롬프트를 공유할 수 있게 한다."""

    class FeatureType(models.TextChoices):
        CHAT = "CHAT", "채팅"
        COACHING = "COACHING", "코칭"
        GENERATE = "GENERATE", "생성"

    prompt_id = models.BigAutoField(primary_key=True)
    feature_type = models.CharField(max_length=20, choices=FeatureType.choices)
    system_instruction = models.TextField()
    version = models.CharField(max_length=20, default="v1.0")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "AI_Prompts"

    def __str__(self):
        return f"{self.feature_type} {self.version}"


class AIUsageLog(models.Model):
    """팀 공통 ERD의 AI_Usage_Logs 테이블. AI 호출 1건마다 한 행씩 남긴다."""

    class FeatureType(models.TextChoices):
        CHAT = "CHAT", "채팅"
        COACHING = "COACHING", "코칭"
        GENERATE = "GENERATE", "생성"

    log_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ai_usage_logs"
    )
    prd = models.ForeignKey(
        PRDProject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
    )
    feature_type = models.CharField(max_length=20, choices=FeatureType.choices)
    total_tokens = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "AI_Usage_Logs"

    def __str__(self):
        return f"{self.feature_type} log #{self.log_id}"


class AIChatHistory(models.Model):
    """팀 공통 ERD의 AI_Chat_Histories 테이블.

    (prd, section, user) 하나당 행 하나 — 메시지마다 새 행을 만들지 않고,
    chat_data JSON 배열 하나를 통째로 갱신(UPSERT)한다.
    """

    chat_id = models.BigAutoField(primary_key=True)
    prd = models.ForeignKey(PRDProject, on_delete=models.CASCADE, related_name="chat_histories")
    section = models.ForeignKey(
        PRDSection,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_histories",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_chat_histories"
    )
    chat_data = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "AI_Chat_Histories"
        constraints = [
            models.UniqueConstraint(
                fields=("prd", "section", "user"), name="ideas_chat_history_unique"
            )
        ]

    def __str__(self):
        return f"chat history #{self.chat_id} ({self.user_id}/{self.section_id})"
