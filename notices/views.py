from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import is_operations_user
from notices.forms import NoticeForm
from notices.models import Notice
from notices.services import delete_notice, notice_rows, save_notice, toggle_notice_publish


def _require_operations(user):
    if not is_operations_user(user):
        raise PermissionDenied


@login_required
def portal(request):
    _require_operations(request.user)
    return render(request, "notices/portal.html", {"notices": notice_rows()})


@login_required
@require_POST
def notice_create(request):
    _require_operations(request.user)
    form = NoticeForm(request.POST)
    if form.is_valid():
        save_notice(form=form, actor=request.user)
        messages.success(request, "공지를 등록했습니다.")
    else:
        messages.error(request, "공지를 저장하지 못했습니다. 제목과 내용을 확인해 주세요.")
    return redirect("notices:portal")


@login_required
@require_POST
def notice_edit(request, notice_id):
    _require_operations(request.user)
    notice = get_object_or_404(Notice, pk=notice_id)
    form = NoticeForm(request.POST, instance=notice)
    if form.is_valid():
        save_notice(form=form, actor=request.user)
        messages.success(request, "공지를 수정했습니다.")
    else:
        messages.error(request, "공지를 저장하지 못했습니다. 제목과 내용을 확인해 주세요.")
    return redirect("notices:portal")


@login_required
@require_POST
def notice_delete(request, notice_id):
    _require_operations(request.user)
    try:
        delete_notice(notice_id=notice_id, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(getattr(error, "messages", [str(error)])))
    else:
        messages.success(request, "공지를 삭제했습니다.")
    return redirect("notices:portal")


@login_required
@require_POST
def notice_toggle_publish(request, notice_id):
    _require_operations(request.user)
    try:
        notice = toggle_notice_publish(notice_id=notice_id, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(getattr(error, "messages", [str(error)])))
    else:
        messages.success(
            request,
            "공지를 공개했습니다." if notice.is_published else "공지를 비공개로 전환했습니다.",
        )
    return redirect("notices:portal")
