from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import User, WhitelistEmail
from .forms import SignUpForm, LoginForm, OnboardingForm


def login_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            remember_login = request.POST.get('remember_login')

            user = authenticate(request, username=email, password=password)

            if user is not None:
                if user.approval_status == User.ApprovalStatus.PENDING:
                    messages.warning(request, '아직 승인 검토 중입니다. 튜터의 승인을 기다려주세요.')
                    return render(request, 'accounts/login.html', {'form': form})
                
                if user.approval_status == User.ApprovalStatus.REJECTED:
                    messages.error(request, '승인이 거절되었습니다. 관리자에게 문의하세요.')
                    return render(request, 'accounts/login.html', {'form': form})

                login(request, user)

                if remember_login:
                    request.session.set_expiry(60 * 60 * 24 * 30)  # 30일 세션 유지
                else:
                    request.session.set_expiry(0)  # 브라우저 종료 시 만료

                if not user.is_onboarded:
                    return redirect('accounts:onboarding')

                return redirect('accounts:dashboard')
            else:
                messages.error(request, '이메일 또는 비밀번호가 올바르지 않습니다.')
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})


def signup_view(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            if user.approval_status == User.ApprovalStatus.APPROVED:
                messages.success(request, '사전 등록 계정으로 확인되어 자동 승인되었습니다! 로그인해 주세요.')
            else:
                messages.info(request, '회원가입이 완료되었습니다. 튜터 승인 후 로그인이 가능합니다.')
            return redirect('accounts:login')
    else:
        form = SignUpForm()

    return render(request, 'accounts/signup.html', {'form': form})


@require_POST
def signup_api(request):
    """모달 전용 비동기 회원가입 API"""
    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip()
    password = request.POST.get('password', '').strip()
    password_confirm = request.POST.get('password_confirm', '').strip()

    if not name or not email or not password:
        return JsonResponse({'success': False, 'message': '모든 필수 항목을 입력해주세요.'}, status=400)

    if password != password_confirm:
        return JsonResponse({'success': False, 'message': '비밀번호가 일치하지 않습니다.'}, status=400)

    if len(password) < 6:
        return JsonResponse({'success': False, 'message': '비밀번호는 최소 6자 이상이어야 합니다.'}, status=400)

    if User.objects.filter(email=email).exists():
        return JsonResponse({'success': False, 'message': '이미 가입된 이메일 주소입니다.'}, status=400)

    whitelist_entry = WhitelistEmail.objects.filter(email=email).first()
    if whitelist_entry:
        approval_status = User.ApprovalStatus.APPROVED
        role = whitelist_entry.role
        session_info = whitelist_entry.session_info
        is_auto_approved = True
    else:
        approval_status = User.ApprovalStatus.PENDING
        role = User.Role.STUDENT
        session_info = ''
        is_auto_approved = False

    user = User.objects.create_user(
        username=email,
        email=email,
        password=password,
        first_name=name,
        role=role,
        approval_status=approval_status,
        session_info=session_info
    )

    if is_auto_approved:
        msg = f'사전 등록된 수강생({name})으로 확인되어 자동 승인되었습니다! 바로 로그인해 주세요.'
    else:
        msg = '회원가입 신청이 완료되었습니다! 튜터 심사 후 로그인이 승인됩니다.'

    return JsonResponse({
        'success': True,
        'is_auto_approved': is_auto_approved,
        'email': user.email,
        'message': msg
    })


@require_POST
def verify_user_for_reset_api(request):
    """비밀번호 찾기 Step 1: 이름 + 이메일 일치 여부 확인"""
    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip()

    if not name or not email:
        return JsonResponse({'success': False, 'message': '이름과 이메일을 모두 입력해주세요.'}, status=400)

    user = User.objects.filter(email=email, first_name=name).first()
    if not user:
        user = User.objects.filter(email=email, username=name).first()

    if user:
        if user.is_social_account:
            return JsonResponse({'success': False, 'message': '구글 소셜 연동 계정은 구글 로그인으로 접속해 주세요.'}, status=400)
        return JsonResponse({
            'success': True,
            'user_id': user.id,
            'name': user.first_name or user.username,
            'email': user.email,
            'message': '사용자 정보가 확인되었습니다.'
        })
    else:
        return JsonResponse({'success': False, 'message': '일치하는 회원 정보를 찾을 수 없습니다.'}, status=404)


@require_POST
def reset_password_api(request):
    """비밀번호 찾기 Step 2: 새 비밀번호 변경 적용"""
    user_id = request.POST.get('user_id')
    new_password = request.POST.get('new_password', '').strip()
    new_password_confirm = request.POST.get('new_password_confirm', '').strip()

    if not user_id or not new_password:
        return JsonResponse({'success': False, 'message': '새 비밀번호를 입력해주세요.'}, status=400)

    if new_password != new_password_confirm:
        return JsonResponse({'success': False, 'message': '새 비밀번호가 서로 일치하지 않습니다.'}, status=400)

    if len(new_password) < 6:
        return JsonResponse({'success': False, 'message': '비밀번호는 최소 6자 이상이어야 합니다.'}, status=400)

    try:
        user = User.objects.get(id=user_id)
        user.set_password(new_password)
        user.save()
        return JsonResponse({
            'success': True,
            'email': user.email,
            'message': '비밀번호가 성공적으로 재설정되었습니다. 새 비밀번호로 로그인해 주세요.'
        })
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'message': '사용자를 찾을 수 없습니다.'}, status=404)


def logout_view(request):
    logout(request)
    return redirect('accounts:login')


@login_required
def onboarding_view(request):
    if request.user.is_onboarded:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = OnboardingForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save(commit=False)
            user.first_name = form.cleaned_data['name']
            user.is_onboarded = True
            user.save()
            messages.success(request, '온보딩이 완료되었습니다! 대시보드로 이동합니다.')
            return redirect('accounts:dashboard')
    else:
        form = OnboardingForm(instance=request.user, initial={'name': request.user.first_name})

    return render(request, 'accounts/onboarding.html', {'form': form})


SAMPLE_FEEDBACKS = {
    'tutor': [
        {"author": "박교수 튜터", "week": "8주차 파이널", "date": "2026.08.15", "content": "전체 아키텍처 구조가 매우 견고하며, Redis 캐싱 및 비동기 처리 적용이 탁월합니다. 상용 서비스 배포 수준입니다."},
        {"author": "박교수 튜터", "week": "6주차 스프린트", "date": "2026.08.01", "content": "REST API 규격과 상태 코드(HTTP Status) 처리가 표준에 맞게 깔끔하게 정돈되었습니다."},
        {"author": "김멘토 튜터", "week": "4주차 중간점검", "date": "2026.07.18", "content": "DB 쿼리 N+1 문제를 select_related로 잘 개선하셨습니다. 데이터베이스 인덱싱 설계도 훌륭합니다."},
        {"author": "박교수 튜터", "week": "2주차 과제", "date": "2026.07.04", "content": "기본 모델링 구조가 탄탄합니다. 온보딩 가드 로직 설계가 인상적입니다."}
    ],
    'team': [
        {"team_name": "2팀 (Beta)", "week": "8주차 파이널", "date": "2026.08.14", "content": "대시보드의 우선순위 정렬 UX와 반응형 사이드바가 아주 매끄럽게 동작하여 사용성이 최고였습니다."},
        {"team_name": "4팀 (Delta)", "week": "7주차 크로스리뷰", "date": "2026.08.07", "content": "마이페이지 5각 레이더 차트의 시각화 완성도가 높고 강점/약점 분석 태그가 직관적입니다."},
        {"team_name": "1팀 (Alpha)", "week": "5주차 크로스리뷰", "date": "2026.07.24", "content": "가입 승인 대기 큐에서 비동기 처리로 새로고침 없이 승인/거절되는 인터랙션이 인상 깊었습니다."},
        {"team_name": "3팀 (Gamma)", "week": "3주차 크로스리뷰", "date": "2026.07.11", "content": "API 예외 처리가 꼼꼼하고 토스트 알림 디자인이 깔끔합니다."}
    ],
    'peer': [
        {"author": "익명의 팀원 A", "week": "8주차 파이널", "content": "8주 동안 팀장으로서 모든 일정 조율과 병목 이슈를 완벽히 해결해 주셨습니다. 함께해서 든든했습니다!"},
        {"author": "익명의 팀원 B", "week": "7주차 스프린트", "content": "프론트엔드 모달과 차트 연동 작업을 밤샘 작업 없이 완벽한 일정 안에 끝낼 수 있게 리드해 주셨습니다."},
        {"author": "익명의 팀원 C", "week": "5주차 스프린트", "content": "의견 충돌이 있을 때마다 중재를 잘해주시고 명확한 근거를 바탕으로 의사결정을 이끌어주셨습니다."},
        {"author": "익명의 팀원 D", "week": "2주차 스프린트", "content": "Git 브랜치 전략과 컨벤션을 명확히 잡아주셔서 협업 충돌 없이 편하게 개발했습니다."}
    ]
}

WEEKS_HISTORY = [
    {"week": 7, "team": "3팀 (Alpha)", "members": "이수진, 박도현, 김민준", "grade": "A+ (97점)", "peer_score": "4.85 / 5.0", "repo": "github.com/team3/final-prep"},
    {"week": 6, "team": "3팀 (Alpha)", "members": "이수진, 박도현, 김민준", "grade": "A (93점)", "peer_score": "4.70 / 5.0", "repo": "github.com/team3/api-perf"},
    {"week": 5, "team": "2팀 (Beta)", "members": "최민아, 강태호, 김민준", "grade": "A+ (98점)", "peer_score": "4.90 / 5.0", "repo": "github.com/team2/async-queue"},
    {"week": 4, "team": "2팀 (Beta)", "members": "최민아, 강태호, 김민준", "grade": "A (95점)", "peer_score": "4.75 / 5.0", "repo": "github.com/team2/midterm-proto"},
    {"week": 3, "team": "1팀 (Alpha)", "members": "윤아름, 정유진, 김민준", "grade": "A (92점)", "peer_score": "4.60 / 5.0", "repo": "github.com/team1/eval-core"},
    {"week": 2, "team": "1팀 (Alpha)", "members": "윤아름, 정유진, 김민준", "grade": "B+ (88점)", "peer_score": "4.45 / 5.0", "repo": "github.com/team1/auth-skeleton"},
    {"week": 1, "team": "5팀 (Epsilon)", "members": "오세훈, 배수지, 김민준", "grade": "A (91점)", "peer_score": "4.50 / 5.0", "repo": "github.com/team5/onboarding-ux"},
]


@login_required
def dashboard_view(request):
    if not request.user.is_onboarded:
        return redirect('accounts:onboarding')
    return render(request, 'accounts/dashboard.html', {'current_week': 8, 'feedbacks': SAMPLE_FEEDBACKS})


@login_required
def mypage_view(request):
    context = {
        'current_week': 8,
        'feedbacks': SAMPLE_FEEDBACKS,
        'recent_feedbacks': [
            {"badge": "튜터 피드백", "badge_class": "bg-primary", "week": "8주차 파이널", "text": "전체 아키텍처 구조가 매우 견고하며, Redis 캐싱 및 비동기 처리 적용이 탁월합니다."},
            {"badge": "팀 과제 피드백", "badge_class": "bg-warning text-dark", "week": "8주차 리뷰", "text": "대시보드의 우선순위 정렬 UX와 반응형 사이드바가 아주 매끄럽게 동작합니다."},
            {"badge": "동료 피드백", "badge_class": "bg-secondary", "week": "8주차 파이널", "text": "8주 동안 팀장으로서 모든 일정 조율과 병목 이슈를 완벽히 해결해 주셨습니다."}
        ],
        'weeks_history': WEEKS_HISTORY,
        'competencies': {
            'teamwork': 4.8,
            'problem_solving': 4.5,
            'responsibility': 4.7,
            'dev_knowledge': 4.2,
            'communication': 4.9,
            'total_avg': 4.62,
            'feedback_count': 12
        }
    }
    return render(request, 'accounts/mypage.html', context)


@login_required
def tutor_admin_view(request):
    pending_users = User.objects.filter(approval_status=User.ApprovalStatus.PENDING).order_by('-date_joined')
    students = User.objects.filter(role=User.Role.STUDENT, approval_status=User.ApprovalStatus.APPROVED).order_by('first_name')
    return render(request, 'accounts/tutor_admin.html', {
        'current_week': 8,
        'pending_users': pending_users,
        'students': students,
        'feedbacks': SAMPLE_FEEDBACKS,
    })


@login_required
@require_POST
def approve_user_api(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN] and not request.user.is_staff:
        return JsonResponse({'success': False, 'message': '권한이 없습니다.'}, status=403)
    try:
        target_user = User.objects.get(id=user_id)
        target_user.approval_status = User.ApprovalStatus.APPROVED
        target_user.save()
        return JsonResponse({'success': True, 'message': f'{target_user.first_name or target_user.username} 학생이 승인되었습니다.'})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'message': '사용자를 찾을 수 없습니다.'}, status=404)


@login_required
@require_POST
def reject_user_api(request, user_id):
    if request.user.role not in [User.Role.TUTOR, User.Role.ADMIN] and not request.user.is_staff:
        return JsonResponse({'success': False, 'message': '권한이 없습니다.'}, status=403)
    try:
        target_user = User.objects.get(id=user_id)
        target_user.approval_status = User.ApprovalStatus.REJECTED
        target_user.save()
        return JsonResponse({'success': True, 'message': f'{target_user.first_name or target_user.username} 학생 가입이 거절되었습니다.'})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'message': '사용자를 찾을 수 없습니다.'}, status=404)


@login_required
@require_POST
def update_profile_api(request):
    """마이페이지: 프로필 정보(이름, 연락처) 및 비밀번호 변경 API"""
    try:
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        current_password = request.POST.get('current_password', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        new_password_confirm = request.POST.get('new_password_confirm', '').strip()

        if not name:
            return JsonResponse({'success': False, 'message': '이름을 입력해주세요.', 'error_field': 'name'})

        user = request.user
        password_changed = False

        if new_password or current_password or new_password_confirm:
            if user.is_social_account:
                return JsonResponse({'success': False, 'message': '소셜 로그인 계정은 비밀번호를 변경할 수 없습니다.'})

            if not current_password:
                return JsonResponse({
                    'success': False, 
                    'error_field': 'current_password', 
                    'message': '현재 사용 중인 기존 비밀번호를 입력해주세요.'
                })

            if not user.check_password(current_password):
                return JsonResponse({
                    'success': False, 
                    'error_field': 'current_password', 
                    'message': '기존 비밀번호가 일치하지 않습니다. 다시 확인해 주세요.'
                })

            if not new_password:
                return JsonResponse({
                    'success': False, 
                    'error_field': 'new_password', 
                    'message': '새 비밀번호를 입력해주세요.'
                })

            if len(new_password) < 6:
                return JsonResponse({
                    'success': False, 
                    'error_field': 'new_password', 
                    'message': '새 비밀번호는 최소 6자 이상이어야 합니다.'
                })

            if new_password != new_password_confirm:
                return JsonResponse({
                    'success': False, 
                    'error_field': 'new_password_confirm', 
                    'message': '새 비밀번호와 비밀번호 확인이 서로 일치하지 않습니다.'
                })

            user.set_password(new_password)
            user.save()
            update_session_auth_hash(request, user)
            password_changed = True

        user.first_name = name
        user.phone = phone
        user.save()

        msg = '비밀번호가 성공적으로 변경되었습니다.' if password_changed else '프로필 정보가 수정되었습니다.'

        return JsonResponse({
            'success': True,
            'password_changed': password_changed,
            'message': msg,
            'data': {'name': user.first_name, 'phone': user.phone}
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'처리 중 오류가 발생했습니다: {str(e)}'})