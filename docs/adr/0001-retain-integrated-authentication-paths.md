---
status: accepted
---

# 통합된 인증 경로 유지

정제 요구사항과 `TECHNICAL_DECISIONS.md`의 초기 MVP 인증은 비밀번호와 사전 등록 Google 로그인으로 제한하지만, 현재 `main`에는 공개 회원가입·Google·Kakao 로그인·화이트리스트 승인 흐름이 팀 작업으로 이미 통합되어 있다. 이 ADR은 현재 통합 범위에 한해 다음 조항만 대체한다.

- `docs/REFINED-REQUIREMENTS.md`의 Google 외 소셜·공개 가입·화이트리스트 제외 항목, AUTH-004의 단일 제공자 범위, AUTH-005의 `User.google_sub` 저장, AUTH-006의 사전 등록 계정 전용 최초 연결, AUTH-009의 비밀번호 세션 고정 수명, DEC-009의 제공자·가입 경계
- `docs/TECHNICAL_DECISIONS.md`의 Google 단일 제공자와 User 직접 `sub` 저장 결정
- `docs/DATABASE-DESIGN.md` 5.1의 `STUDENT|TUTOR` 전용 role schema와 `google_sub` 컬럼, 범용 `SocialAccount` 테이블 금지 조항

AUTH-007의 Google state·nonce 검증은 Kakao의 state 검증과 함께 확장해 유지한다. AUTH-008의 token 비영속은 두 제공자에 그대로 적용하며, AUTH-009의 소셜 세션 14일 규칙도 유지한다. 나머지 권한·세션·업무 데이터 결정은 그대로 유효하다. 이번 하드닝에서는 팀 작업을 삭제하거나 숨기지 않고 모든 지원 인증 경로를 함께 정리하며, 미병합 인증 브랜치의 변경은 포함하지 않는다.

## Consequences

비밀번호 회원가입은 이메일 소유 확인 전까지 활성화하지 않는다. 학생 화이트리스트 사용자는 이메일 소유 확인 후 자동 승인하고, 일반 사용자는 확인 후에도 튜터 승인을 기다린다. 화이트리스트만으로 튜터·관리자 권한을 자동 부여하지 않는다. Google·Kakao는 공급자가 검증한 이메일만 가입·연결에 사용하며, 소셜 계정의 불변 식별자는 django-allauth `SocialAccount(provider, uid)`다. 토큰은 저장하지 않는다.

지원 인증 경로마다 비밀정보 관리, 계정 연결 충돌, 승인 상태, 로그인 실패 제한과 회귀 테스트를 동일한 기준으로 검증해야 한다. rounds·teams·reviews·results·audit 평가 업무 테이블은 변경하지 않지만, `accounts_user`의 역할 제약과 인증 상태 필드를 확장하고 django-allauth·throttle 등 인증 지원 테이블과 이메일 전달 인프라를 사용한다. 정제 요구사항의 전체 MVP 경계는 후속 문서 정합성 작업에서 재검토한다.
