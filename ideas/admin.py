from django.contrib import admin

from .models import (
    AIPrompt,
    AIUsageLog,
    PRDProject,
    PRDQuestion,
    PRDSection,
    PostIt,
    PostItConnection,
)


class PRDQuestionInline(admin.TabularInline):
    model = PRDQuestion
    extra = 0


class PRDSectionInline(admin.TabularInline):
    model = PRDSection
    extra = 0
    show_change_link = True


@admin.register(PRDProject)
class PRDProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "project_type", "status", "deadline", "created_by", "updated_at")
    list_filter = ("project_type", "status")
    search_fields = ("title", "description")
    inlines = [PRDSectionInline]


@admin.register(PRDSection)
class PRDSectionAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "step", "order")
    inlines = [PRDQuestionInline]


@admin.register(PostIt)
class PostItAdmin(admin.ModelAdmin):
    list_display = ("content", "project", "status", "author", "assignee")
    list_filter = ("status",)


admin.site.register(PostItConnection)


@admin.register(AIPrompt)
class AIPromptAdmin(admin.ModelAdmin):
    list_display = ("feature_type", "version", "is_active")
    list_filter = ("feature_type", "is_active")


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ("user", "prd", "feature_type", "total_tokens", "created_at")
    list_filter = ("feature_type",)
