# 문서 안내

이 디렉터리의 문서는 아래 순서로 읽는다. 문서가 충돌하면
`REFINED-REQUIREMENTS.md`를 구현과 인수 테스트의 최종 기준으로 사용한다.

## 구현 기준 문서

1. [`REFINED-REQUIREMENTS.md`](REFINED-REQUIREMENTS.md)
   - 2단계 리뷰를 통과한 최종 요구사항과 인수 기준
2. [`FLOWS.md`](FLOWS.md)
   - 기능 흐름, 역할별 이동, 페이지별 정상·예외 동작
3. [`DATABASE-DESIGN.md`](DATABASE-DESIGN.md)
   - 12개 업무 테이블, 관계, 제약, 트랜잭션과 마이그레이션 순서
4. [`TECHNICAL_DECISIONS.md`](TECHNICAL_DECISIONS.md)
   - 기술 스택, 앱 책임, 인증, 권한과 구현 원칙

## UI와 개발 규칙

5. [`DESIGN.md`](DESIGN.md)
   - 공통 시각 언어와 디자인 토큰
6. [`LAYOUT.md`](LAYOUT.md)
   - 애플리케이션 셸, 그리드와 반응형 레이아웃
7. [`CODING_CONVENTIONS.md`](CODING_CONVENTIONS.md)
   - Python·Django·템플릿·테스트·Git 규칙

## 분석 및 과거 기준

8. [`PROJECT_ANALYSIS_REPORT.md`](PROJECT_ANALYSIS_REPORT.md)
   - 초기 프로젝트와 개인 제안의 불일치, 통합 결정 및 구현 현황
9. [`REQUIREMENTS.md`](REQUIREMENTS.md)
   - 분석 당시 통합 요구사항. 현재 구현 기준으로 사용하지 않음

개인별 초안이 있던 `team-docs` 디렉터리는 통합 완료 후 제거했다. 필요한 판단 근거는
`PROJECT_ANALYSIS_REPORT.md`와 `REFINED-REQUIREMENTS.md`의 리뷰 기록에 남아 있다.
