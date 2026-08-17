from django.contrib import admin

from reviews.models import ReviewAnswer, ReviewSubmission


class ReviewAnswerInline(admin.TabularInline):
    model = ReviewAnswer
    extra = 0
    readonly_fields = ("question", "rating_value", "text_value", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReviewSubmission)
class ReviewSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "round",
        "review_type",
        "evaluator",
        "target_team",
        "target_participant",
        "submitted_at",
    )
    list_filter = ("review_type", "round")
    readonly_fields = (
        "round",
        "review_type",
        "evaluator",
        "target_team",
        "target_participant",
        "submitted_at",
    )
    inlines = (ReviewAnswerInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReviewAnswer)
class ReviewAnswerAdmin(admin.ModelAdmin):
    readonly_fields = ("submission", "question", "rating_value", "text_value", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
