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

MVP 소셜 인증은 Google OIDC 로그인만 지원한다. 범용 소셜 계정·토큰 테이블은 만들지 않는다.

---

## 2. 권장 Django App 경계

```text
accounts/
rounds/
teams/
reviews/
results/
audit/
```

### accounts

- 인증
- 학생 식별 정보
- 학생 대시보드

### rounds

- 평가 회차
- 평가 기간
- `QuestionTemplate(category=TEAM|PEER)` 질문지 템플릿
- `TemplateQuestion` 템플릿 소속 평가 문항
- 진행 상태

### teams

- 팀
- 팀 구성원
- 자동 초기 배치
- 같은 편집 화면의 수동 팀 구성 조정
- 최종 Team·Membership 저장

자동·수동 구분, 후보 상태, 편성 실행 이력은 저장하지 않는다.

### reviews

- `review_type=TEAM|PEER` 공통 평가 제출
- 공통 문항 응답
- 대상 유형·자기 평가·중복 평가 검증
- 팀·개인 평가 기능별 서비스와 화면

### results

- 개인 최종점수
- 팀 / 개인 순위
- 결과 조회
- 계산 실행 버전과 공개 시각
- `result_type=TEAM|INDIVIDUAL` 공통 결과 행
- 활성 결과에서 조회 시 계산하는 다음 평가용 Seed

### audit

- 회차 시작·강제 마감
- 팀 구성 저장
- 채점·재채점·공개 변경 감사

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

세부 계산 기준은 `results` 앱 구현 시 `docs/REFINED-REQUIREMENTS.md`(RES-001~RES-017,
SUB-004~SUB-006)로 확정했다. 요약:

- **무응답은 0점이 아니라 N/A.** 유효 제출이 하나도 없는 팀·개인은 평균에서 제외하는 게
  아니라 N/A로 처리하고, 순위·Seed 이력에서도 제외한다. 최종점수는 구성 점수(팀 점수·
  개인 점수) 중 하나라도 N/A면 N/A다.
- **정밀도는 raw와 표시를 분리한다.** 제출 점수부터 팀/개인 점수·최종점수·Seed까지 계산
  체인 전체는 raw 정밀도(소수 6자리, `*_raw` 컬럼과 동일)를 유지하고, 화면에 보여줄 때만
  `ROUND_HALF_UP`으로 소수 둘째 자리로 반올림한다(`display_score`). 매 계산 단계마다
  2자리로 반올림하면 오차가 누적되므로 하지 않는다.
- **순위는 경쟁 순위.** 공개 점수 기준 내림차순, 동점은 같은 순위를 받고 다음 순위는
  인원수만큼 건너뛴다 (`1, 2, 2, 4`). N/A는 순위에서 제외한다.
- **Seed는 최근 최대 3개 유효 최종점수를 오래된 순 20%·30%·50%로 가중 평균한다.** 3개
  미만이면 가중치를 뒤(최근)에서부터 잘라 재정규화한다 - 2개면 30%+50%를, 1개면 50%를
  100%로 (REFINED-REQUIREMENTS.md AC-10 예시로 검증: 과거 4.0, 최신 5.0 → 4.625). N/A
  회차는 이력에서 제외하고, 유효 이력이 없으면 무시드(N/A)로 처리하며 0점으로 대체하지
  않는다.

구현은 `results/services.py`의 순수 함수(모델 의존 없음)로 되어 있다.

---

## 6. 결과 공개

공개는 회차 전체를 한 번에 켜고 끄는 단일 스위치가 아니라, 다음 4개 항목을 각각 독립적으로
공개한다 (RES-010): 팀 1위, 전체 팀 순위, 본인 최종·구성 점수, 본인 개인 순위. 각 항목은
공개 시각(`*_published_at`)을 갖는다 - 아직 공개 전이면 null이다.

학생 화면은 공개된 항목만 노출한다.

관리자는 학생 공개 여부와 관계없이 필요한 전체 결과를 확인할 수 있어야 한다.

**Seed는 이 공개 설정과 무관하다.** 회차 결과 공개 여부와 상관없이 항상 계산·조회 가능한
내부용 데이터다 (RES-017) - 다음 회차 자동 편성이 결과 공개를 기다릴 필요가 없다.

재채점하면 새 계산 버전을 만들고 4개 공개 항목을 모두 다시 비공개로 되돌린다 (RES-009).

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

Google 로그인은 backend authorization code flow를 사용한다. ID Token의 `sub`만 User에
영속화하고 code·ID/access token은 검증 후 폐기하며 refresh token은 요청하지 않는다.
`state`·`nonce`는 5분짜리 일회성 Django 세션에 두고 인증 성공 후 세션 키를 회전해 14일짜리
로그인 세션으로 전환한다. `SESSION_EXPIRE_AT_BROWSER_CLOSE=False`이므로 같은 브라우저를
닫았다 열어도 만료 전에는 로그인이 유지된다.

평가 템플릿은 여러 회차가 재사용한다. 튜터는 회차에서 등록된 TEAM·PEER 템플릿을 선택하고
개별 문항은 편집하지 않는다. Django staff 운영 관리자가 템플릿 마스터를 등록하며, 시작된
회차가 참조한 템플릿과 문항은 불변이다. 변경이 필요하면 원본 대신 복제본을 등록해 다른
DRAFT 회차에 연결한다.

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
