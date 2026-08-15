from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import User, WhitelistEmail
from .forms import SignUpForm, LoginForm, OnboardingForm

def login_view(request):
    """
    로그인 및 승인 상태별 분기 처리
    """
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, username=email, password=password)

            if user is not None:
                # 1. 승인 대기 상태 검사
                if user.approval_status == User.ApprovalStatus.PENDING:
                    messages.warning(request, '아직 승인 검토 중입니다. 튜터의 승인을 기다려주세요.')
                    return render(request, 'accounts/login.html', {'form': form})
                
                # 2. 승인 거절 상태 검사
                if user.approval_status == User.ApprovalStatus.REJECTED:
                    messages.error(request, '승인이 거절되었습니다. 관리자에게 문의하세요.')
                    return render(request, 'accounts/login.html', {'form': form})

                # 3. 정상 로그인
                login(request, user)

                # 4. 온보딩 가드 확인
                if not user.is_onboarded:
                    return redirect('accounts:onboarding')

                return redirect('accounts:dashboard')
            else:
                messages.error(request, '이메일 또는 비밀번호가 올바르지 않습니다.')
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})


def signup_view(request):
    """
    회원가입 뷰
    """
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


def logout_view(request):
    """
    로그아웃 뷰
    """
    logout(request)
    return redirect('accounts:login')


@login_required
def onboarding_view(request):
    """
    온보딩 가드 뷰: 필수 정보 입력 완료 전까지 대시보드 이동 차단
    """
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


@login_required
def dashboard_view(request):
    """
    학생 메인 대시보드 뷰
    """
    if not request.user.is_onboarded:
        return redirect('accounts:onboarding')
    return render(request, 'accounts/dashboard.html')


@login_required
def mypage_view(request):
    """
    마이페이지 뷰
    """
    return render(request, 'accounts/mypage.html')


@login_required
def tutor_admin_view(request):
    """
    튜터 학생 관리 콘솔 뷰
    """
    pending_users = User.objects.filter(approval_status=User.ApprovalStatus.PENDING)
    students = User.objects.filter(role=User.Role.STUDENT, approval_status=User.ApprovalStatus.APPROVED)
    return render(request, 'accounts/tutor_admin.html', {
        'pending_users': pending_users,
        'students': students
    })