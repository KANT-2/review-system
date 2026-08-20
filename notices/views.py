from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
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
def notice_detail_json(request, notice_id):
    """알림에서 공지 클릭 시 모달에 띄울 내용 - 대시보드 공지 바 밖에서도 열 수 있어야 한다.

    비공개로 전환됐거나 삭제된 공지는 알림에 남아 있어도 더 이상 원문을 보여주지 않는다.
    """
    notice = get_object_or_404(Notice, pk=notice_id, is_published=True)
    return JsonResponse(
        {
            "title": notice.title,
            "content": notice.content,
            "created_at": notice.created_at.isoformat(),
        }
    )


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
