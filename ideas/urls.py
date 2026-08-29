from django.urls import path

from . import views

app_name = "ideas"

urlpatterns = [
    path("", views.home, name="home"),
    path("new/", views.prd_new, name="prd_new"),
    path("<int:pk>/", views.prd_write, name="prd_write"),
    path("<int:pk>/status/", views.prd_update_status, name="prd_update_status"),
    path("save-answer/", views.prd_save_answer, name="prd_save_answer"),
    path("save-section-title/", views.prd_update_section_title, name="prd_save_section_title"),
    path("save-question-text/", views.prd_update_question_text, name="prd_save_question_text"),
    path("<int:pk>/brainstorm/", views.brainstorm, name="brainstorm"),
    path("<int:pk>/brainstorm/sync/", views.brainstorm_sync, name="brainstorm_sync"),
    path("<int:pk>/ai-coach/", views.ai_coach_ask, name="ai_coach_ask"),
    path("<int:pk>/ai-coach/history/", views.ai_coach_history, name="ai_coach_history"),
    path("<int:pk>/ai-coach/draft/", views.ai_coach_draft, name="ai_coach_draft"),
]
