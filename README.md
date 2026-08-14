# AX Evaluation Console

AX Evaluation Console is a Django + PostgreSQL web application for managing recurring student project evaluations.

The system supports the overall evaluation cycle:

```text
Student Registration
→ Team Assignment
→ Assignment / Presentation
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

### 5. Prepare PostgreSQL

Make sure PostgreSQL is installed and running.

Create the local database and user required by the values in your `.env` file.

Each developer should use a local development database unless the team explicitly decides otherwise.

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

Detailed rules and implementation decisions are intentionally kept outside this README.

- [`AGENT.md`](AGENT.md)  
  Repository working rules for developers and coding agents.

- [`docs/DESIGN.md`](docs/DESIGN.md)  
  Shared visual design language and design tokens.

- [`docs/LAYOUT.md`](docs/LAYOUT.md)  
  Global application shell, Sidebar / Top Bar / Main Content layout, grid, and responsive behavior.

- [`docs/TECHNICAL_DECISIONS.md`](docs/TECHNICAL_DECISIONS.md)  
  Technology choices, application boundaries, architecture decisions, scoring rules, and implementation decisions.

- [`docs/CODING_CONVENTIONS.md`](docs/CODING_CONVENTIONS.md)  
  Python, Django, template, testing, linting, formatting, and commit conventions.

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
