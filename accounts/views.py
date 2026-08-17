import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.forms import LoginForm, SignUpForm
from accounts.models import User, WhitelistEmail
from reviews.models import Review

# ==========================================
# 1. 템플릿 렌더링 뷰
# ==========================================


def login_view(request):
    """로그인 뷰 (로그인 유지 및 승인 상태 제어).

    역할(학생/튜터/관리자)에 관계없이 로그인 후에는 동일한 대시보드로 이동한다.
    튜터/관리자 전용 기능은 별도 페이지로 리다이렉트하지 않고, 사이드바의
    "튜터 관리 / 승인" 메뉴(승인된 튜터·관리자에게만 노출)를 통해 접근한다.
    """
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            user = form.get_user()
            if user.approval_status == User.ApprovalStatus.PENDING:
                messages.warning(
                    request, "아직 가입 승인 검토 중입니다. 튜터의 승인을 기다려주세요."
                )
                return redirect("accounts:login")
            elif user.approval_status == User.ApprovalStatus.REJECTED:
                messages.error(request, "승인이 거절된 계정입니다. 관리자에게 문의하세요.")
                return redirect("accounts:login")

            login(request, user, backend="django.contrib.auth.backends.ModelBackend")

            if not request.POST.get("remember_session"):
                request.session.set_expiry(0)

            return redirect("accounts:dashboard")
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form})


def home_view(request):
    """루트 경로('/') 접근 시 로그인 상태에 따라 자동 분기 리다이렉트"""
    if not request.user.is_authenticated:
        return redirect("accounts:login")

    return redirect("accounts:dashboard")


def signup_view(request):
    """회원가입 뷰 (로그인 화면의 가입 모달이 기본 경로이며, 이 뷰는 폴백 페이지)"""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_onboarded = False
            whitelist = WhitelistEmail.objects.filter(email=user.email).first()

            if whitelist:
                user.approval_status = User.ApprovalStatus.APPROVED
                user.role = whitelist.role
                user.session_info = whitelist.session_info
                user.save()
                messages.success(request, "사전 승인된 계정입니다. 로그인해 주세요.")
            else:
                user.approval_status = User.ApprovalStatus.PENDING
                user.role = User.Role.STUDENT
                user.save()
                messages.warning(
                    request, "가입 신청이 완료되었습니다. 튜터 승인 후 이용 가능합니다."
                )

            return redirect("accounts:login")
    else:
        form = SignUpForm()

    return render(request, "accounts/signup.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


def _build_feedback_center_context(user):
    """대시보드/마이페이지에서 여는 공용 '피드백 확인' 모달(templates/base.html의
    #feedbackModal)에 채워 넣을 데이터를 만든다. 대시보드와 마이페이지가 같은 모달을
    공유하기 때문에 dashboard_view, mypage_view 양쪽에서 이 함수를 호출한다.

    - 튜터 피드백: reviews 앱의 Review 모델에 실제로 저장된 데이터를 조회한다.
    - 팀 과제 피드백 / 동료 상호 피드백: team_reviews, peer_reviews 앱에는 아직 데이터를
      저장할 모델이 없어서 빈 목록으로 둔다. 두 앱에 모델이 생기면 이 함수 안에서
      각각 채워주면 된다.
    """
    tutor_reviews = (
        Review.objects.filter(student=user).select_related("tutor").order_by("-created_at")
    )
    tutor_feedbacks = [
        {
            "author": (review.tutor.first_name or review.tutor.email) if review.tutor else "튜터",
            "week": review.title,
            "date": timezone.localtime(review.created_at).strftime("%Y.%m.%d"),
            "content": review.content,
        }
        for review in tutor_reviews
    ]
    team_feedbacks = []
    peer_feedbacks = []

    return {
        "feedbacks": {
            "tutor": tutor_feedbacks,
            "team": team_feedbacks,
            "peer": peer_feedbacks,
        },
        "total_feedback_count": len(tutor_feedbacks) + len(team_feedbacks) + len(peer_feedbacks),
    }


@login_required
def dashboard_view(request):
    """메인 대시보드 (진행 중 라운드, 동료 평가 목록, 팀 정보).

    학생/튜터/관리자 모두 동일한 화면을 본다. 튜터·관리자에게는 사이드바에
    "튜터 관리 / 승인" 메뉴가 추가로 노출되어 별도의 튜터 콘솔로 이동할 수 있다.
    """
    # 평가 라운드 및 팀 피어 데이터 구성
    team_peers = [
        {
            "id": 101,
            "name": "김민수",
            "role_in_team": "기획 / 데이터 분석",
            "task_summary": "LLM 프롬프트 엔지니어링 및 데이터 전처리",
            "is_evaluated": False,
        },
        {
            "id": 102,
            "name": "이지은",
            "role_in_team": "프론트엔드",
            "task_summary": "대시보드 UI 구현 및 API 연동",
            "is_evaluated": False,
        },
        {
            "id": 103,
            "name": "박준호",
            "role_in_team": "백엔드 / DB",
            "task_summary": "Django ORM 및 인증 파이프라인 구축",
            "is_evaluated": True,
        },
    ]

    total_peers = len(team_peers)
    evaluated_count = sum(1 for p in team_peers if p["is_evaluated"])
    progress_percent = int((evaluated_count / total_peers * 100)) if total_peers > 0 else 0

    context = {
        "user": request.user,
        "my_team_name": "AX 3팀 (Alpha Innovators)",
        "team_project_topic": "생성형 AI 기반 기업 내부 문서 검색 & 평가 자동화 플랫폼",
        "current_round": {
            "name": "1차 프로젝트 스프린트 피어 리뷰",
            "deadline": timezone.now() + timedelta(days=3),
        },
        "team_peers": team_peers,
        "total_peers_count": total_peers,
        "evaluated_count": evaluated_count,
        "progress_percent": progress_percent,
        **_build_feedback_center_context(request.user),
    }
    return render(request, "accounts/dashboard.html", context)


@login_required
def mypage_view(request):
    """마이페이지 (5대 역량 레이더 차트 및 정성 피드백 리포트)"""
    competency_labels = [
        "AI 도구 활용",
        "문제 정의 및 기획",
        "기술 완성도",
        "팀 협업 및 책임감",
        "커뮤니케이션",
    ]
    my_scores = [88, 82, 85, 94, 90]
    avg_scores = [78, 75, 76, 82, 80]

    competency_details = [
        {"label": lbl, "score": sc} for lbl, sc in zip(competency_labels, my_scores, strict=False)
    ]

    peer_feedbacks = [
        {
            "round_name": "1차 프로젝트 피어 리뷰",
            "comment": "기획 단계에서 AI 도구를 적극적으로 도입하여 분석 시간을 대폭 단축해 주셨습니다.",
        },
        {
            "round_name": "1차 프로젝트 피어 리뷰",
            "comment": "팀 내 이슈가 발생했을 때 즉각적인 커뮤니케이션으로 조율해 주셔서 든든했습니다.",
        },
        {
            "round_name": "0차 사전 과제 리뷰",
            "comment": "코드 구조가 깔끔하고 문서화가 잘 되어 있어 협업하기 매우 편했습니다.",
        },
    ]

    # 주차별 상세 이력 (팀/라운드 모델이 아직 없어 대시보드의 team_peers와 같은 방식으로
    # 목업 데이터를 둔다). 최신 주차(7주차)가 먼저 오도록 정렬 - 화면 로드시 JS가 7주차를
    # 기본으로 보여준다.
    weeks_history = [
        {
            "week": 7,
            "team": "Alpha",
            "members": "이수진, 박도현, 김민준",
            "repo": "github.com/ax-team3/final-sprint",
            "grade": "A (우수)",
            "peer_score": "4.7 / 5.0",
        },
        {
            "week": 6,
            "team": "Alpha",
            "members": "이수진, 박도현, 김민준",
            "repo": "github.com/ax-team3/mid-sprint",
            "grade": "B+ (양호)",
            "peer_score": "4.5 / 5.0",
        },
        {
            "week": 5,
            "team": "Beta",
            "members": "최민아, 강태호, 김민준",
            "repo": "github.com/ax-team2/week5-prototype",
            "grade": "A (우수)",
            "peer_score": "4.6 / 5.0",
        },
        {
            "week": 4,
            "team": "Beta",
            "members": "최민아, 강태호, 김민준",
            "repo": "github.com/ax-team2/week4-mvp",
            "grade": "B (보통)",
            "peer_score": "4.3 / 5.0",
        },
        {
            "week": 3,
            "team": "Gamma",
            "members": "윤아름, 정유진, 김민준",
            "repo": "github.com/ax-team1/week3-wireframe",
            "grade": "A- (우수)",
            "peer_score": "4.4 / 5.0",
        },
        {
            "week": 2,
            "team": "Gamma",
            "members": "윤아름, 정유진, 김민준",
            "repo": "github.com/ax-team1/week2-architecture",
            "grade": "B+ (양호)",
            "peer_score": "4.2 / 5.0",
        },
        {
            "week": 1,
            "team": "Gamma",
            "members": "윤아름, 정유진, 김민준",
            "repo": "github.com/ax-team1/week1-problem-def",
            "grade": "B (보통)",
            "peer_score": "4.0 / 5.0",
        },
    ]

    feedback_center_context = _build_feedback_center_context(request.user)

    context = {
        "user": request.user,
        "competency_labels": json.dumps(competency_labels),
        "competency_scores": json.dumps(my_scores),
        "competency_avg_scores": json.dumps(avg_scores),
        "competency_details": competency_details,
        "avg_score": round(sum(my_scores) / len(my_scores), 1),
        "received_reviews_count": len(peer_feedbacks) + 3,
        "peer_feedbacks": peer_feedbacks,
        "weeks_history": weeks_history,
        # 프로필 배너의 "누적 피드백 수"와 피드백 모달은 같은 실제 데이터를 공유한다.
        "competencies": {"feedback_count": feedback_center_context["total_feedback_count"]},
        **feedback_center_context,
    }
    return render(request, "accounts/mypage.html", context)


@login_required
def tutor_dashboard(request):
    """튜터 관리 콘솔 (가입 승인 대기 큐 + 등록 학생 목록/피드백 작성).

    대시보드/마이페이지와 동일한 base.html 디자인 시스템(accounts/tutor_admin.html)을
    사용한다. 사이드바의 "튜터 관리 / 승인" 메뉴는 승인된 튜터/관리자에게만 노출되지만,
    URL을 직접 입력해 접근하는 경우를 대비해 권한 체크는 그대로 유지한다.
    """
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        messages.error(request, "튜터 전용 페이지입니다.")
        return redirect("accounts:dashboard")

    pending_users = User.objects.filter(approval_status=User.ApprovalStatus.PENDING).order_by(
        "-date_joined"
    )
    students = User.objects.filter(
        role=User.Role.STUDENT, approval_status=User.ApprovalStatus.APPROVED
    ).order_by("first_name", "email")
    approved_students_count = students.count()
    whitelist_count = WhitelistEmail.objects.count()

    context = {
        "pending_users": pending_users,
        "students": students,
        "approved_students_count": approved_students_count,
        "whitelist_count": whitelist_count,
    }
    return render(request, "accounts/tutor_admin.html", context)


@login_required
@require_POST
def approve_user(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        messages.error(request, "권한이 없습니다.")
        return redirect("accounts:dashboard")

    if request.method == "POST":
        target_user = get_object_or_404(User, id=user_id)
        target_user.approval_status = User.ApprovalStatus.APPROVED
        target_user.save()
        messages.success(request, f"{target_user.email} 계정이 승인되었습니다.")
    return redirect("accounts:tutor_admin")


@login_required
@require_POST
def reject_user(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        messages.error(request, "권한이 없습니다.")
        return redirect("accounts:dashboard")

    if request.method == "POST":
        target_user = get_object_or_404(User, id=user_id)
        target_user.approval_status = User.ApprovalStatus.REJECTED
        target_user.save()
        messages.warning(request, f"{target_user.email} 계정이 반려되었습니다.")
    return redirect("accounts:tutor_admin")


# ==========================================
# 2. 비동기 JSON API
# ==========================================


@login_required
@require_POST
def api_onboarding(request):
    """온보딩 정보 저장 비동기 API"""
    try:
        data = json.loads(request.body)
        user = request.user
        first_name = data.get("first_name")
        session_info = data.get("session_info")
        phone_number = data.get("phone_number")

        if not first_name or not session_info or not phone_number:
            return JsonResponse(
                {"success": False, "message": "모든 필수 항목을 입력해 주세요."}, status=400
            )

        user.first_name = first_name
        user.session_info = session_info
        user.phone_number = phone_number
        user.is_onboarded = True
        user.save()

        return JsonResponse({"success": True, "message": "온보딩이 완료되었습니다."})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@login_required
@require_POST
def update_profile_api(request):
    """프로필 수정 비동기 API"""
    try:
        data = json.loads(request.body)
        user = request.user
        if "first_name" in data:
            user.first_name = data["first_name"]
        if "phone_number" in data:
            user.phone_number = data["phone_number"]
        if "session_info" in data:
            user.session_info = data["session_info"]

        user.save()
        return JsonResponse({"success": True, "message": "프로필이 수정되었습니다."})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@require_POST
def signup_api(request):
    """회원가입 비동기 API (로그인 화면의 가입 모달이 호출).

    이메일/비밀번호만 받는다 - 이름, 기수, 연락처는 승인 후 첫 로그인 시 뜨는 온보딩
    모달(api_onboarding)에서 따로 받는다.
    """
    try:
        data = json.loads(request.body)
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()

        if not email or not password:
            return JsonResponse(
                {"success": False, "message": "이메일과 비밀번호를 모두 입력해 주세요."}, status=400
            )

        if User.objects.filter(email=email).exists():
            return JsonResponse(
                {"success": False, "message": "이미 가입된 이메일입니다."}, status=400
            )

        whitelist = WhitelistEmail.objects.filter(email=email).first()
        user = User(email=email, is_onboarded=False)
        user.set_password(password)

        if whitelist:
            user.approval_status = User.ApprovalStatus.APPROVED
            user.role = whitelist.role
            user.session_info = whitelist.session_info
            user.save()
            return JsonResponse(
                {
                    "success": True,
                    "approved": True,
                    "message": "사전 승인된 계정으로 가입되었습니다. 로그인해 주세요.",
                }
            )
        else:
            user.approval_status = User.ApprovalStatus.PENDING
            user.role = User.Role.STUDENT
            user.save()
            return JsonResponse(
                {
                    "success": True,
                    "approved": False,
                    "message": "가입 신청되었습니다. 튜터 승인 후 로그인 시 온보딩이 진행됩니다.",
                }
            )
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@require_POST
def verify_user_for_reset_api(request):
    """비밀번호 재설정 1단계: 이메일 + 연락처로 본인 확인 (로그인 화면의 '비밀번호를
    잊으셨나요?' 모달이 호출)."""
    try:
        data = json.loads(request.body)
        email = data.get("email")
        phone_number = data.get("phone_number")

        user = User.objects.filter(email=email).first()
        if not user:
            return JsonResponse(
                {"success": False, "message": "해당 이메일의 사용자를 찾을 수 없습니다."},
                status=404,
            )

        if (
            phone_number
            and user.phone_number
            and user.phone_number.replace("-", "") != phone_number.replace("-", "")
        ):
            return JsonResponse(
                {"success": False, "message": "등록된 연락처와 일치하지 않습니다."}, status=400
            )

        return JsonResponse({"success": True, "message": "본인 인증이 완료되었습니다."})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@require_POST
def reset_password_api(request):
    """비밀번호 재설정 2단계: 본인 확인이 끝난 이메일의 비밀번호를 새 비밀번호로 저장."""
    try:
        data = json.loads(request.body)
        email = data.get("email")
        new_password = data.get("new_password")

        user = User.objects.filter(email=email).first()
        if not user:
            return JsonResponse(
                {"success": False, "message": "사용자를 찾을 수 없습니다."}, status=404
            )

        user.set_password(new_password)
        user.save()
        return JsonResponse({"success": True, "message": "비밀번호가 성공적으로 변경되었습니다."})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


@login_required
@require_POST
def approve_user_api(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        return JsonResponse({"success": False, "message": "권한이 없습니다."}, status=403)
    user = get_object_or_404(User, id=user_id)
    user.approval_status = User.ApprovalStatus.APPROVED
    user.save()
    return JsonResponse({"success": True, "message": f"{user.email} 계정이 승인되었습니다."})


@login_required
@require_POST
def reject_user_api(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        return JsonResponse({"success": False, "message": "권한이 없습니다."}, status=403)
    user = get_object_or_404(User, id=user_id)
    user.approval_status = User.ApprovalStatus.REJECTED
    user.save()
    return JsonResponse({"success": True, "message": f"{user.email} 계정이 반려되었습니다."})
