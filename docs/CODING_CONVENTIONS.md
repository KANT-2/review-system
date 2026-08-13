# CODING_CONVENTIONS.md

이 문서는 AX 평가 시스템의 코딩 스타일과 자동 품질 검사 기준을 정의한다.

목표는 “잘하는 사람만 읽을 수 있는 코드”가 아니라 **팀원 누구나 읽고 수정하기 쉬운 코드**를 만드는 것이다.

---

## 1. 기본 원칙

- 코드의 짧음보다 읽기 쉬움을 우선한다.
- 하나의 함수는 가능한 한 하나의 역할만 맡는다.
- 이름만 보고 역할을 짐작할 수 있게 작성한다.
- 같은 문제를 이미 해결한 기존 코드가 있으면 그 패턴을 재사용한다.
- 복잡한 한 줄 코드보다 여러 줄의 명확한 코드를 선호한다.
- 필요 없는 추상화나 디자인 패턴을 미리 만들지 않는다.

---

## 2. Python 스타일

Python 코드는 PEP 8과 기존 Django 코드 스타일을 기본으로 하되, 이 프로젝트 설정을 우선한다.

### 들여쓰기

Python은 공백 4칸을 사용한다.

```python
def calculate_score(team_score, peer_score):
    final_score = team_score * 0.4 + peer_score * 0.6
    return final_score
```

Tab과 Space를 섞지 않는다.

### 줄 길이

프로젝트의 Python 최대 줄 길이는 **100자**를 기준으로 한다.

100자를 넘는 코드는 괄호를 활용해 자연스럽게 줄바꿈한다.

### 이름 규칙

```text
파일 / 모듈       snake_case.py
함수              snake_case()
변수              snake_case
클래스 / Model    PascalCase
상수              UPPER_SNAKE_CASE
```

좋은 예:

```python
class TeamEvaluation(models.Model):
    ...

def calculate_final_score():
    ...

MAX_TEAM_COUNT = 10
```

피할 예:

```python
class team_evaluation:
    ...

def CalculateScore():
    ...

x1 = ...
```

식별자에는 가능한 한 영어 단어를 사용한다.

사용자에게 보이는 문구는 한국어로 작성할 수 있다.

---

## 3. Import 규칙

Import는 파일 상단에 작성하고 다음 그룹으로 나눈다.

1. Python 표준 라이브러리
2. 외부 패키지 / Django
3. 프로젝트 내부 App

예:

```python
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from teams.models import Team
from .models import TeamEvaluation
```

`from module import *` 형태의 wildcard import는 사용하지 않는다.

Import 정렬은 Ruff가 자동으로 확인한다.

---

## 4. Django 코드 역할 분리

코드를 어디에 넣어야 할지 애매할 때 아래 기준을 사용한다.

### `models.py`

데이터 구조와 데이터베이스 수준의 제약을 정의한다.

### `forms.py`

사용자가 입력한 값이 올바른지 확인한다.

### `views.py`

HTTP 요청을 받고 권한을 확인한 뒤 적절한 동작을 연결한다.

View 안에 긴 점수 계산이나 자동편성 알고리즘을 작성하지 않는다.

### `services.py`

여러 단계가 필요한 비즈니스 로직을 둔다.

예:

```text
점수 계산
순위 계산
자동 팀 편성
평가 종료 처리
```

### `admin.py`

튜터 / 관리자가 Django Admin에서 관리할 기능을 정의한다.

### `tests.py` 또는 `tests/`

정상 동작과 예외 상황을 자동으로 검증한다.

### Template

데이터를 보여주는 역할에 집중한다.

복잡한 계산이나 핵심 비즈니스 규칙을 Template 안에 구현하지 않는다.

---

## 5. 함수 작성 규칙

함수 이름에는 동작이 드러나야 한다.

좋은 예:

```python
calculate_final_score()
create_balanced_teams()
can_evaluate_team()
get_current_evaluation_round()
```

피할 예:

```python
process()
handle()
do_work()
func1()
```

함수가 너무 길어져 여러 단계의 일을 처리하면 역할별 함수 또는 Service로 분리할지 검토한다.

단, 단순한 코드를 억지로 여러 함수로 쪼개지는 않는다.

---

## 6. Boolean 이름

Boolean 값은 True / False 의미가 이름에 드러나게 한다.

좋은 예:

```python
is_active
is_submitted
can_evaluate
has_previous_score
```

피할 예:

```python
active
check
status_flag
value
```

---

## 7. Django Model 규칙

Model 이름은 단수형 `PascalCase`를 사용한다.

```python
Team
TeamMembership
EvaluationRound
PeerEvaluation
```

ForeignKey 필드는 대상이 명확하도록 작성한다.

```python
evaluation_round
evaluator
target_student
target_team
```

중복 저장이나 잘못된 관계를 DB 수준에서 막을 수 있다면 Constraint 사용을 검토한다.

모델 변경 전에는 다른 App에서 해당 필드를 사용하는지 확인한다.

---

## 8. Django Template / HTML 스타일

HTML과 Django Template은 공백 2칸 들여쓰기를 사용한다.

`{% extends %}`는 주석을 제외하고 Template의 첫 번째 Django tag가 되도록 한다.

Django Template 표현식에는 안쪽 공백을 둔다.

좋은 예:

```django
{{ student.name }}

{% if evaluation.is_open %}
  ...
{% endif %}
```

피할 예:

```django
{{student.name}}

{%if evaluation.is_open%}
```

Bootstrap 5.3 컴포넌트와 Utility를 우선 사용한다.

반복되는 스타일이 아니라면 페이지마다 새로운 CSS 클래스를 만들지 않는다.

큰 Inline CSS / Inline JavaScript는 피한다.

UI 디자인 기준은 `DESIGN.md`를 따른다.

---

## 9. 주석과 Docstring

코드를 그대로 읽으면 알 수 있는 내용을 반복해서 주석으로 작성하지 않는다.

나쁜 예:

```python
# 점수에 0.4를 곱한다.
team_score = team_score * 0.4
```

좋은 주석은 “왜 이렇게 했는지”를 설명한다.

```python
# RFP의 최종점수 기준에 따라 팀 점수는 40%만 반영한다.
weighted_team_score = team_score * Decimal("0.4")
```

복잡한 Service 함수나 외부에서 사용하는 함수는 필요한 경우 Docstring으로 목적과 중요한 조건을 설명한다.

---

## 10. 예외 처리

넓은 `except Exception:`으로 문제를 숨기지 않는다.

가능하면 예상 가능한 예외를 구체적으로 처리한다.

사용자가 잘못된 요청을 보낸 경우에도 서버 오류가 아니라 적절한 Validation 또는 HTTP 응답으로 처리한다.

---

## 11. 테스트 이름

테스트 이름만 보고 어떤 상황을 검증하는지 알 수 있어야 한다.

권장:

```python
def test_student_cannot_evaluate_own_team():
    ...

def test_duplicate_team_evaluation_is_rejected():
    ...

def test_final_score_uses_team_40_peer_60():
    ...
```

피할 예:

```python
def test_1():
    ...

def test_evaluation():
    ...
```

테스트는 가능하면 다음 구조로 읽히게 작성한다.

```text
준비(Arrange)
→ 실행(Act)
→ 확인(Assert)
```

---

## 12. Python 린팅과 포맷팅: Ruff

Python 품질 검사는 Ruff로 통일한다.

### 문제 확인

```bash
ruff check .
```

### 자동 수정 가능한 문제 수정

```bash
ruff check . --fix
```

### Python 코드 자동 정렬

```bash
ruff format .
```

### 포맷이 맞는지만 확인

```bash
ruff format --check .
```

Ruff가 자동으로 고칠 수 있는 변경도 적용 후 diff를 확인한다.

---

## 13. Django Template 검사: djLint

Django Template은 djLint를 사용한다.

### Template 문제 확인

```bash
djlint .
```

### 포맷이 맞는지 확인

```bash
djlint . --check
```

### Template 자동 정렬

```bash
djlint . --reformat
```

프로젝트 설정은 `pyproject.toml`의 Django profile을 따른다.

---

## 14. Django 자체 검사

린터가 통과해도 Django 설정이나 Model 문제가 있을 수 있다.

코드 변경 후 다음 검사를 함께 사용한다.

```bash
python manage.py check
```

기능 테스트:

```bash
python manage.py test
```

Model을 변경했다면 Migration 상태도 확인한다.

```bash
python manage.py makemigrations --check
```

필요한 Migration이 있다면 실제 Migration 파일을 생성하고 함께 Commit한다.

---

## 15. 커밋 전 권장 검사 순서

자동 수정:

```bash
ruff check . --fix
ruff format .
djlint . --reformat
```

검증:

```bash
ruff check .
ruff format --check .
djlint . --check
python manage.py check
python manage.py test
```

Model 변경이 있다면 추가:

```bash
python manage.py makemigrations --check
```

모든 명령을 무조건 외울 필요는 없다.

`pre-commit`을 설정하면 기본적인 포맷과 린트 검사는 Commit 직전에 자동으로 실행된다.

---

## 16. pre-commit

최초 1회 개발 도구를 설치한다.

```bash
pip install -r requirements-dev.txt
pre-commit install
```

전체 파일을 수동 검사하고 싶을 때:

```bash
pre-commit run --all-files
```

pre-commit이 파일을 자동 수정했다면 변경 내용을 확인하고 다시 Commit한다.

자동 검사 실패를 피하기 위해 `--no-verify`로 우회하는 것을 기본 해결 방법으로 사용하지 않는다.

---

## 17. Commit Convention

커밋 제목 형식:

```text
<type>: <변경 내용>
```

선택적으로 scope를 사용한다.

```text
<type>(<scope>): <변경 내용>
```

### Type

`feat`
: 새로운 사용자 기능

`fix`
: 잘못된 동작이나 버그 수정

`refactor`
: 기능 동작은 같지만 코드 구조를 개선

`test`
: 테스트 추가 또는 수정

`docs`
: Markdown, README 등 문서 변경

`style`
: 공백, 정렬 등 동작에 영향을 주지 않는 코드 스타일 변경

`chore`
: 개발 설정, 패키지, 린터 등의 유지보수

`ci`
: GitHub Actions 등 CI 설정

### 좋은 예

```text
feat(team-review): 팀 평가 제출 기능 추가
fix(peer-review): 자기 평가가 저장되는 문제 수정
refactor(results): 최종 점수 계산 로직을 서비스로 분리
test(teams): 자동편성 인원 균형 테스트 추가
docs: 개발 환경 설정 방법 추가
chore: Ruff와 djLint 설정 추가
```

### 피할 예

```text
수정
update
fix
최종
진짜최종
여러개 수정
```

커밋 설명은 한국어를 사용해도 된다.

한 커밋에서 한 가지 목적이 드러나도록 작성한다.

---

## 18. 자동화 도구의 역할

각 도구가 하는 일은 서로 다르다.

```text
Ruff
→ Python 코드의 문제와 스타일을 검사하고 포맷한다.

djLint
→ Django Template HTML의 문제와 정렬을 검사한다.

Django check
→ Django 설정, Model 구성 등의 프레임워크 문제를 검사한다.

Django test
→ 우리가 정한 실제 기능과 비즈니스 규칙을 검증한다.

pre-commit
→ Commit 직전에 위와 같은 검사를 자동 실행하는 연결 장치다.
```

린터가 통과했다고 기능이 올바른 것은 아니다.

따라서 **Lint + Django Check + Test**를 서로 다른 안전장치로 생각한다.
