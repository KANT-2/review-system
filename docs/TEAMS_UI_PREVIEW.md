# 팀 편성 UI 검토 방법

이 미리보기는 다른 파트의 PostgreSQL 모델이 병합되기 전에도 팀 편성 화면을 검토하기 위한 개발 전용 환경이다. 운영 설정에서는 미리보기 URL이 등록되지 않는다.

## 실행

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행한다.

```powershell
.\.venv\Scripts\python.exe manage.py runserver --settings=config.preview_settings
```

## 화면 주소

- 튜터 편성 화면: <http://127.0.0.1:8000/teams/preview/?role=tutor>
- 튜터 미배정 학생 화면: <http://127.0.0.1:8000/teams/preview/?role=tutor&state=unassigned>
- 튜터 편성 전 화면: <http://127.0.0.1:8000/teams/preview/?role=tutor&state=empty>
- 학생 전체 팀 화면: <http://127.0.0.1:8000/teams/preview/?role=student>
- 학생 편성 전 화면: <http://127.0.0.1:8000/teams/preview/?role=student&state=empty>

튜터 화면에서는 드래그 이동, 팀 수 변경, 자동 배치, 변경 취소와 저장 버튼을 테스트 데이터로 확인할 수 있다. 미리보기에서 저장한 내용은 실제 데이터베이스에 기록되지 않는다.
