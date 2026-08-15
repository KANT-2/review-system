import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta

from accounts.models import User, WhitelistEmail
from accounts.forms import LoginForm, SignUpForm


# ==========================================
# 1. 템플릿 렌더링 뷰
# ==========================================

def login_view(request):
    """로그인 뷰 (로그인 유지 및 승인 상태 제어)"""
    if request.user.is_authenticated:
        if request.user.role in [User.Role.TUTOR, User.Role.ADMIN]:
            return redirect('accounts:tutor_dashboard')
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            user = form.get_user()
            if user.approval_status == User.ApprovalStatus.PENDING:
                messages.warning(request, '아직 가입 승인 검토 중입니다. 튜터의 승인을 기다려주세요.')
                return redirect('accounts:login')
            elif user.approval_status == User.ApprovalStatus.REJECTED:
                messages.error(request, '승인이 거절된 계정입니다. 관리자에게 문의하세요.')
                return redirect('accounts:login')

            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            if not request.POST.get('remember_session'):
                request.session.set_expiry(0)

            if user.role in [User.Role.TUTOR, User.Role.ADMIN]:
                return redirect('accounts:tutor_dashboard')
            return redirect('accounts:dashboard')
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})


def signup_view(request):
    """회원가입 뷰"""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            whitelist = WhitelistEmail.objects.filter(email=user.email).first()

            if whitelist:
                user.approval_status = User.ApprovalStatus.APPROVED
                user.role = whitelist.role
                user.session_info = whitelist.session_info
                user.save()
                messages.success(request, '사전 승인된 계정입니다. 로그인해 주세요.')
            else:
                user.approval_status = User.ApprovalStatus.PENDING
                user.role = User.Role.STUDENT
                user.save()
                messages.warning(request, '가입 신청이 완료되었습니다. 튜터 승인 후 이용 가능합니다.')

            return redirect('accounts:login')
    else:
        form = SignUpForm()

    return render(request, 'accounts/signup.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('accounts:login')


@login_required
def dashboard_view(request):
    """수강생 메인 대시보드 (진행 중 라운드, 동료 평가 목록, 팀 정보)"""
    if request.user.role in [User.Role.TUTOR, User.Role.ADMIN]:
        return redirect('accounts:tutor_dashboard')

    # 평가 라운드 및 팀 피어 데이터 구성
    team_peers = [
        {'id': 101, 'name': '김민수', 'role_in_team': '기획 / 데이터 분석', 'task_summary': 'LLM 프롬프트 엔지니어링 및 데이터 전처리', 'is_evaluated': False},
        {'id': 102, 'name': '이지은', 'role_in_team': '프론트엔드', 'task_summary': '대시보드 UI 구현 및 API 연동', 'is_evaluated': False},
        {'id': 103, 'name': '박준호', 'role_in_team': '백엔드 / DB', 'task_summary': 'Django ORM 및 인증 파이프라인 구축', 'is_evaluated': True},
    ]

    total_peers = len(team_peers)
    evaluated_count = sum(1 for p in team_peers if p['is_evaluated'])
    progress_percent = int((evaluated_count / total_peers * 100)) if total_peers > 0 else 0

    context = {
        'user': request.user,
        'my_team_name': 'AX 3팀 (Alpha Innovators)',
        'team_project_topic': '생성형 AI 기반 기업 내부 문서 검색 & 평가 자동화 플랫폼',
        'current_round': {
            'name': '1차 프로젝트 스프린트 피어 리뷰',
            'deadline': timezone.now() + timedelta(days=3),
        },
        'team_peers': team_peers,
        'total_peers_count': total_peers,
        'evaluated_count': evaluated_count,
        'progress_percent': progress_percent,
    }
    return render(request, 'accounts/dashboard.html', context)


@login_required
def mypage_view(request):
    """마이페이지 (5대 역량 레이더 차트 및 정성 피드백 리포트)"""
    competency_labels = [
        'AI 도구 활용',
        '문제 정의 및 기획',
        '기술 완성도',
        '팀 협업 및 책임감',
        '커뮤니케이션'
    ]
    my_scores = [88, 82, 85, 94, 90]
    avg_scores = [78, 75, 76, 82, 80]

    competency_details = [
        {'label': lbl, 'score': sc} for lbl, sc in zip(competency_labels, my_scores)
    ]

    peer_feedbacks = [
        {'round_name': '1차 프로젝트 피어 리뷰', 'comment': '기획 단계에서 AI 도구를 적극적으로 도입하여 분석 시간을 대폭 단축해 주셨습니다.'},
        {'round_name': '1차 프로젝트 피어 리뷰', 'comment': '팀 내 이슈가 발생했을 때 즉각적인 커뮤니케이션으로 조율해 주셔서 든든했습니다.'},
        {'round_name': '0차 사전 과제 리뷰', 'comment': '코드 구조가 깔끔하고 문서화가 잘 되어 있어 협업하기 매우 편했습니다.'},
    ]

    context = {
        'user': request.user,
        'competency_labels': json.dumps(competency_labels),
        'competency_scores': json.dumps(my_scores),
        'competency_avg_scores': json.dumps(avg_scores),
        'competency_details': competency_details,
        'avg_score': round(sum(my_scores) / len(my_scores), 1),
        'received_reviews_count': len(peer_feedbacks) + 3,
        'peer_feedbacks': peer_feedbacks,
    }
    return render(request, 'accounts/mypage.html', context)


@login_required
def tutor_dashboard(request):
    """튜터 콘솔"""
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        messages.error(request, '튜터 전용 페이지입니다.')
        return redirect('accounts:dashboard')

    pending_users = User.objects.filter(approval_status=User.ApprovalStatus.PENDING).order_by('-date_joined')
    approved_students_count = User.objects.filter(role=User.Role.STUDENT, approval_status=User.ApprovalStatus.APPROVED).count()
    whitelist_count = WhitelistEmail.objects.count()

    context = {
        'pending_users': pending_users,
        'approved_students_count': approved_students_count,
        'whitelist_count': whitelist_count,
    }
    return render(request, 'accounts/tutor_dashboard.html', context)


@login_required
def approve_user(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        messages.error(request, '권한이 없습니다.')
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        target_user.approval_status = User.ApprovalStatus.APPROVED
        target_user.save()
        messages.success(request, f"{target_user.email} 계정이 승인되었습니다.")
    return redirect('accounts:tutor_dashboard')


@login_required
def reject_user(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        messages.error(request, '권한이 없습니다.')
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        target_user.approval_status = User.ApprovalStatus.REJECTED
        target_user.save()
        messages.warning(request, f"{target_user.email} 계정이 반려되었습니다.")
    return redirect('accounts:tutor_dashboard')


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
        first_name = data.get('first_name')
        session_info = data.get('session_info')
        phone_number = data.get('phone_number')

        if not first_name or not session_info or not phone_number:
            return JsonResponse({'success': False, 'message': '모든 필수 항목을 입력해 주세요.'}, status=400)

        user.first_name = first_name
        user.session_info = session_info
        user.phone_number = phone_number
        user.is_onboarded = True
        user.save()

        return JsonResponse({'success': True, 'message': '온보딩이 완료되었습니다.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
@require_POST
def update_profile_api(request):
    """프로필 수정 비동기 API"""
    try:
        data = json.loads(request.body)
        user = request.user
        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'phone_number' in data:
            user.phone_number = data['phone_number']
        if 'session_info' in data:
            user.session_info = data['session_info']

        user.save()
        return JsonResponse({'success': True, 'message': '프로필이 수정되었습니다.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_POST
def signup_api(request):
    try:
        data = json.loads(request.body)
        email = data.get('email')
        password = data.get('password')
        first_name = data.get('first_name', '')
        phone_number = data.get('phone_number', '')

        if not email or not password:
            return JsonResponse({'success': False, 'message': '이메일과 비밀번호는 필수입니다.'}, status=400)

        if User.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'message': '이미 가입된 이메일입니다.'}, status=400)

        whitelist = WhitelistEmail.objects.filter(email=email).first()
        user = User(email=email, first_name=first_name, phone_number=phone_number)
        user.set_password(password)

        if whitelist:
            user.approval_status = User.ApprovalStatus.APPROVED
            user.role = whitelist.role
            user.session_info = whitelist.session_info
            user.save()
            return JsonResponse({'success': True, 'approved': True, 'message': '사전 승인된 계정으로 가입되었습니다.'})
        else:
            user.approval_status = User.ApprovalStatus.PENDING
            user.role = User.Role.STUDENT
            user.save()
            return JsonResponse({'success': True, 'approved': False, 'message': '가입 신청되었습니다. 튜터 승인을 기다려주세요.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_POST
def verify_user_for_reset_api(request):
    try:
        data = json.loads(request.body)
        email = data.get('email')
        phone_number = data.get('phone_number')

        user = User.objects.filter(email=email).first()
        if not user:
            return JsonResponse({'success': False, 'message': '해당 이메일의 사용자를 찾을 수 없습니다.'}, status=404)

        if phone_number and user.phone_number and user.phone_number.replace('-', '') != phone_number.replace('-', ''):
            return JsonResponse({'success': False, 'message': '등록된 연락처와 일치하지 않습니다.'}, status=400)

        return JsonResponse({'success': True, 'message': '본인 인증이 완료되었습니다.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_POST
def reset_password_api(request):
    try:
        data = json.loads(request.body)
        email = data.get('email')
        new_password = data.get('new_password')

        user = User.objects.filter(email=email).first()
        if not user:
            return JsonResponse({'success': False, 'message': '사용자를 찾을 수 없습니다.'}, status=404)

        user.set_password(new_password)
        user.save()
        return JsonResponse({'success': True, 'message': '비밀번호가 성공적으로 변경되었습니다.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
@require_POST
def approve_user_api(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        return JsonResponse({'success': False, 'message': '권한이 없습니다.'}, status=403)
    user = get_object_or_404(User, id=user_id)
    user.approval_status = User.ApprovalStatus.APPROVED
    user.save()
    return JsonResponse({'success': True, 'message': f'{user.email} 계정이 승인되었습니다.'})


@login_required
@require_POST
def reject_user_api(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN]:
        return JsonResponse({'success': False, 'message': '권한이 없습니다.'}, status=403)
    user = get_object_or_404(User, id=user_id)
    user.approval_status = User.ApprovalStatus.REJECTED
    user.save()
    return JsonResponse({'success': True, 'message': f'{user.email} 계정이 반려되었습니다.'})