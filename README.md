# AX Evaluation Console

AX Evaluation Console is a Django + PostgreSQL web application for managing recurring student project evaluations.

The system supports the overall evaluation cycle:

```text
Student Registration
→ Round / Question Setup
→ Team Arrangement and Adjustment
→ Team Evaluation
→ Peer Evaluation
→ Score Calculation
→ Ranking
→ Seed Update
→ Next Team Assignment
```

The project is intended not only to produce a working service, but also to help team members understand how requirements, Django, PostgreSQL, testing, and GitHub collaboration connect in a real web application.

---

## Tech Stack

- Python
- Django
- PostgreSQL
- Django ORM
- Django Template
- Bootstrap 5.3
- Git / GitHub

For detailed technical decisions, see [`docs/TECHNICAL_DECISIONS.md`](docs/TECHNICAL_DECISIONS.md).

---

## Getting Started

Run the following commands from the repository root, where `manage.py` is located.

### 1. Clone the repository

```bash
git clone https://github.com/KANT-2/review-system.git
cd review-system
```

### 2. Create a virtual environment

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

Application dependencies:

```bash
pip install -r requirements.txt
```

Development tools:

```bash
pip install -r requirements-dev.txt
```

### 4. Configure environment variables

Create your local environment file from the example file.

macOS / Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Update `.env` with your local PostgreSQL connection information and other required values.

Do not commit `.env` or real credentials.

Uploaded files (profile photos) are stored under `MEDIA_ROOT`, which defaults to `media/` in the
project directory and is served by the development server only. Set `DJANGO_MEDIA_ROOT` to a
persistent volume path in production and let the web server in front of Django serve `MEDIA_URL`.

### 5. Prepare PostgreSQL

The Docker Compose stack provides PostgreSQL.

```bash
docker compose up -d db
```

The application does not send mail, so no SMTP service is required for development.

### 6. Apply migrations

```bash
python manage.py migrate
```

### 7. Check the Django project

```bash
python manage.py check
```

### 8. Create an admin account

Optional, but recommended for local development.

```bash
python manage.py createsuperuser
```

### 9. Run the development server

```bash
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

가입 사용자는 로그인 화면의 가입 모달에서 이메일과 비밀번호를 함께 입력합니다. 학생
화이트리스트에 등록된 주소는 바로 승인되고, 나머지는 튜터 승인을 기다립니다. 승인 뒤 최초
로그인 때 이름·기수·연락처를 받는 온보딩 모달이 뜹니다.

발송 도메인의 PTR(reverse DNS)을 설정할 수 없어 이메일 소유 확인 단계는 두지 않습니다.
따라서 이 서비스는 어떤 메일도 보내지 않습니다. 비밀번호 재설정은 가입 이메일과 온보딩 때
등록한 연락처를 함께 확인하는 방식이며, 토큰 링크 방식보다 약하므로 튜터의 "비밀번호 재설정
요구" 기능을 함께 운영하세요.

### Authentication operations

#### Google OAuth

Google Cloud Console에서 Web application OAuth client를 만들고 다음 callback을 Authorized
redirect URI에 정확히 등록합니다. 스킴, 호스트, 포트, 마지막 `/`까지 일치해야 합니다.

```text
http://127.0.0.1:8000/accounts/google/login/callback/
https://서비스도메인/accounts/google/login/callback/
```

그 다음 `.env`에 발급값을 넣습니다.

```dotenv
GOOGLE_OAUTH_ENABLED=True
GOOGLE_OAUTH_CLIENT_ID=발급받은-client-id
GOOGLE_OAUTH_CLIENT_SECRET=발급받은-client-secret
```

#### Kakao OAuth

Kakao Developers에서 카카오 로그인을 활성화하고 REST API key의 Redirect URI에 다음 주소를
등록합니다. 동의 항목에서 카카오계정(이메일)을 제공받도록 설정해야 합니다.

```text
http://127.0.0.1:8000/accounts/kakao/login/callback/
https://서비스도메인/accounts/kakao/login/callback/
```

Client secret 기능이 켜져 있다면 해당 코드를 함께 넣습니다.

```dotenv
KAKAO_OAUTH_ENABLED=True
KAKAO_OAUTH_CLIENT_ID=REST-API-key
KAKAO_OAUTH_CLIENT_SECRET=발급받은-client-secret
```

OAuth secret은 Django admin의 `SocialApp`과 환경변수 양쪽에 중복 등록하지 않습니다.

#### Pre-release checks

운영 전에는 OAuth credential을 환경변수로 주입하고 다음 검사를 통과해야 합니다.

```bash
python manage.py check --deploy --fail-level WARNING
python manage.py check_auth_readiness
python manage.py cleanup_auth_throttles
```

`cleanup_auth_throttles`는 만료된 rate-limit bucket을 정리합니다. 일일 작업으로 실행하세요.
저장소 이력에 포함됐던 기존 OAuth credential은 공급자 콘솔에서 폐기하고 새 callback으로
smoke test해야 합니다.

리버스 프록시를 사용할 때는 신뢰할 proxy IP/CIDR와 hop 수를 명시해야 합니다. OAuth callback
query는 proxy/web access log에 기록하지 마세요. 학생
화이트리스트 변경은 승인된 운영 관리자만 수행하고 Django `LogEntry`를 정기 export해 2인이
검토합니다. 불변 감사 앱이 구현되기 전에는 이 절차가 출시 차단 조건으로 남습니다.

Django Template + Bootstrap does not require a separate frontend build step unless the project later introduces an additional frontend bundler.

---

## Development Checks

Before opening a Pull Request, run the available quality checks.

```bash
ruff check .
ruff format --check .
djlint . --check
python manage.py check
python manage.py test
```

If models were changed, also check migration state:

```bash
python manage.py makemigrations --check
```

To enable pre-commit checks:

```bash
pre-commit install
```

To run all configured hooks manually:

```bash
pre-commit run --all-files
```

---

## Documentation

Start with [`docs/README.md`](docs/README.md), which lists the documents in their intended reading
order and identifies the authoritative baseline.

- [`docs/REFINED-REQUIREMENTS.md`](docs/REFINED-REQUIREMENTS.md) — Authoritative requirements
  and acceptance criteria after two-stage review.
- [`docs/FLOWS.md`](docs/FLOWS.md) — Feature and page flows.
- [`docs/DATABASE-DESIGN.md`](docs/DATABASE-DESIGN.md) — 12-table schema, constraints, and
  transactions.
- [`docs/TECHNICAL_DECISIONS.md`](docs/TECHNICAL_DECISIONS.md) — Architecture and implementation
  decisions.
- [`AGENT.md`](AGENT.md) — Repository working rules.

---

## Git Workflow

```text
Issue
→ Branch
→ Implement
→ Check / Test
→ Commit
→ Push
→ Pull Request
→ Review
→ Merge
```

Commit messages use the following format:

```text
<type>: <summary>
```

Examples:

```text
feat: add team evaluation submission
fix: prevent duplicate peer evaluation
test: add team assignment validation tests
docs: update local setup guide
```

See [`docs/CODING_CONVENTIONS.md`](docs/CODING_CONVENTIONS.md) for the full convention.

---

## Project Priority

When implementation choices conflict, prioritize:

```text
Correctness
> Data Integrity
> Repository Consistency
> Simplicity
> Learnability
> Maintainability
> UI Polish
> Optional Features
```

Complete and verify the MVP and core business rules before expanding optional features.
