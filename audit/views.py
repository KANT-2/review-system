from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render

from accounts.models import User
from accounts.permissions import is_operations_user
from audit.services import ACTION_LABELS, audit_event_rows, recorded_actions
from rounds.models import EvaluationRound

PAGE_SIZE = 50


@login_required
def audit_log(request):
    """감사 로그 조회 - 누가 언제 무엇을 했는지 운영자가 화면에서 확인한다."""
    if not is_operations_user(request.user):
        raise PermissionDenied

    def _int_param(name):
        value = request.GET.get(name)
        return int(value) if value and value.isdigit() else None

    round_id = _int_param("round")
    actor_id = _int_param("actor")
    action = request.GET.get("action") or ""
    events = audit_event_rows(round_id=round_id, action=action or None, actor_id=actor_id)
    page = Paginator(events, PAGE_SIZE).get_page(request.GET.get("page"))
    for event in page:
        event.action_label = ACTION_LABELS.get(event.action, event.action)
    return render(
        request,
        "audit/log.html",
        {
            "page": page,
            "rounds": EvaluationRound.objects.order_by("-created_at").only("id", "title"),
            "actors": User.objects.filter(audit_events__isnull=False).distinct().order_by("email"),
            "actions": [(value, ACTION_LABELS.get(value, value)) for value in recorded_actions()],
            "selected_round": round_id,
            "selected_actor": actor_id,
            "selected_action": action,
        },
    )
