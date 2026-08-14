# TECHNICAL_DECISIONS.md

이 문서는 AX 평가 시스템의 **기술적 결정과 구현 기준**을 기록한다.

`AGENT.md`에는 저장소 작업 규칙만 두고, 아래와 같은 기술 사항은 이 문서에서 관리한다.

---

## 1. 기본 기술 스택

- Python
- Django
- PostgreSQL
- Django ORM
- Django Auth
- Django Template
- Bootstrap 5.3
- Django Admin
- Git / GitHub

소셜 로그인은 필요 시 `django-allauth`를 사용한다.

---

## 2. 권장 Django App 경계

```text
accounts/
rounds/
teams/
team_reviews/
peer_reviews/
results/
```

### accounts

- 인증
- 학생 프로필
- 학생 기본 정보
- 학생 대시보드

### rounds

- 평가 회차
- 과제
- 평가 기간
- 평가 템플릿
- 평가 문항
- 진행 상태
- 결과 공개 설정

### teams

- 팀
- 팀 구성원
- 수동 팀 편성
- 자동 팀 편성
- 팀 구성 수정

### team_reviews

- 다른 팀 평가
- 팀 평가 응답
- 중복 평가 방지
- 팀 점수 산출

### peer_reviews

- 같은 팀원 개인 평가
- 개인 평가 응답
- 자기 평가 방지
- 중복 평가 방지
- 개인 평가점수 산출

### results

- 개인 최종점수
- 팀 / 개인 순위
- 결과 조회
- 누적 Seed
- 다음 평가용 Seed

---

## 3. 책임 분리

각 App이 자기 모델과 핵심 로직을 소유한다.

다른 App의 모델은 참조할 수 있지만, 소유 App 밖에서 핵심 구조를 임의로 바꾸지 않는다.

복잡한 계산이나 배치 로직은 View 안에 길게 작성하지 않고 `services.py` 등으로 분리한다.

권장 역할:

- Model: 데이터 구조 / 제약
- Form: 입력 검증
- View: 요청 / 권한 처리
- Service: 계산 / 배치 / 도메인 로직
- Template: 표현
- Admin: 관리자 CRUD
- Test: 정상 / 예외 검증

---

## 4. 핵심 비즈니스 규칙

### 팀 평가

- 자기 팀 평가 불가
- 다른 팀만 평가 가능
- 동일 회차에서 동일 평가자가 동일 팀을 중복 평가할 수 없음

권장 중복 기준:

```text
evaluation_round + evaluator + target_team
```

### 개인 평가

- 같은 팀 구성원만 평가 가능
- 자기 자신 평가 불가
- 다른 팀 학생 평가 불가
- 동일 회차에서 동일 평가자가 동일 학생을 중복 평가할 수 없음

권장 중복 기준:

```text
evaluation_round + evaluator + target_student
```

---

## 5. 점수 계산

기본 개인 최종점수:

```text
개인 최종점수 = 팀 평가점수 × 40% + 개인 평가점수 × 60%
```

소수점 처리와 동점자 정책은 프로젝트에서 한 번 정한 기준을 전체 기능에 동일하게 적용한다.

---

## 6. 결과 공개

평가 회차별로 관리자가 공개 범위를 설정할 수 있어야 한다.

학생 화면은 해당 설정에 따라 결과를 노출한다.

관리자는 학생 공개 여부와 관계없이 필요한 전체 결과를 확인할 수 있어야 한다.

---

## 7. 다음 팀 자동편성

이전 평가의 개인 최종점수 또는 누적 Seed를 다음 평가의 자동 팀 편성 기준으로 사용할 수 있어야 한다.

목표:

- 팀별 인원 차이를 최소화
- 상위권이 한 팀에 집중되지 않게 함
- 하위권이 한 팀에 집중되지 않게 함
- 자동 편성 이후 관리자 수정 가능

초기 평가처럼 Seed가 없을 경우 별도 초기 배정 규칙을 사용한다.

---

## 8. 인증 및 권한

주요 기능은 로그인 상태를 전제로 한다.

학생 / 관리자 권한을 서버에서 구분한다.

다음 요청은 화면에서 숨기는 것과 별개로 서버에서 차단해야 한다.

- 학생의 관리자 URL 접근
- 자기 팀 평가
- 다른 팀 학생 개인평가
- 자기 자신 개인평가
- 이미 제출한 평가 재제출
- 종료된 평가에 대한 제출

---

## 9. 모델링 기준

모델과 필드 이름은 명시적으로 작성한다.

권장 네이밍 예:

```text
evaluation_round
student
team
evaluator
target_team
target_student
score
submitted_at
```

DB Constraint로 막을 수 있는 핵심 데이터 무결성 문제는 가능한 한 DB에서도 보호한다.

불필요한 범용 `core.models`에 도메인 모델을 몰아넣지 않는다.

---

## 10. UI 구현 기준

UI 디자인 원칙은 [DESIGN.md](DESIGN.md)를 따른다.

Bootstrap 5.3을 구조적 기반으로 사용한다.

권장 구성:

```text
container / container-fluid
row / col-*
card
table / table-responsive
btn
form-control
form-select
form-check
nav
navbar
offcanvas
responsive utilities
```

Custom CSS는 Bootstrap 동작을 대체하기보다 프로젝트의 색상, 간격, 타이포그래피, 레이아웃을 보완하는 용도로 사용한다.

---

## 11. 보안 / 환경 설정

민감정보는 환경변수로 관리한다.

권장:

```text
.env
.env.example
```

`.env`는 Git에 포함하지 않는다.

---

## 12. 변경 관리

새로운 기술적 결정이 생기면 `AGENT.md`보다 이 문서를 먼저 갱신한다.

예:

- App 경계 변경
- 모델 책임 변경
- 점수 계산식 변경
- 자동편성 알고리즘 변경
- 인증 방식 변경
- 새로운 공통 라이브러리 도입

저장소 작업 규칙 자체가 바뀌는 경우에만 `AGENT.md`를 수정한다.
