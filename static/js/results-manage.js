// 결과·공개 화면 전용 스크립트 (튜터 결과 관리 / 학생 내 결과 공용).
document.addEventListener("DOMContentLoaded", () => {
  // "더보기" 버튼 문구를 펼침 상태에 맞춰 바꾼다.
  // (아이콘 회전은 custom.css의 [aria-expanded="true"] 규칙이 처리한다)
  document.querySelectorAll(".ax-toggle-rest").forEach((button) => {
    const targetId = button.getAttribute("data-bs-target");
    const target = targetId ? document.querySelector(targetId) : null;
    const label = button.querySelector(".ax-toggle-label");
    if (!target || !label) return;

    const moreText = button.dataset.moreText;
    target.addEventListener("shown.bs.collapse", () => {
      label.textContent = "접기";
    });
    target.addEventListener("hidden.bs.collapse", () => {
      label.textContent = moreText;
    });
  });

  // 데이터 상태 필터(전체 / 일부 제출 / 미제출) - 표의 행을 data-status 기준으로 숨긴다.
  document.querySelectorAll("[data-result-table]").forEach((section) => {
    const group = section.querySelector(".ax-filter-group");
    if (!group) return;
    const rows = section.querySelectorAll("tbody tr[data-status]");
    const restBody = section.querySelector("tbody.collapse");

    group.querySelectorAll(".ax-filter-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        group.querySelectorAll(".ax-filter-chip").forEach((other) => {
          other.classList.remove("active");
        });
        chip.classList.add("active");
        const filter = chip.dataset.filter;

        let restHasMatch = false;
        rows.forEach((row) => {
          const matched = filter === "ALL" || row.dataset.status === filter;
          row.classList.toggle("ax-row-hidden", !matched);
          if (matched && restBody && restBody.contains(row)) {
            restHasMatch = true;
          }
        });

        // 접혀 있는 나머지 행에 결과가 있으면 자동으로 펼쳐 준다.
        if (restBody && filter !== "ALL" && restHasMatch) {
          bootstrap.Collapse.getOrCreateInstance(restBody, { toggle: false }).show();
        }
      });
    });
  });

  // 점수 계산 비율 안내 툴팁.
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((element) => {
    new bootstrap.Tooltip(element);
  });

  // 튜터 전용 메모 모달 - 클릭한 학생의 이름/기존 메모/저장 주소를 폼에 채워 넣는다.
  const noteModal = document.getElementById("studentNoteModal");
  if (noteModal) {
    const form = noteModal.querySelector("#studentNoteForm");
    const nameLabel = noteModal.querySelector("#noteStudentName");
    const bodyField = noteModal.querySelector("#noteBody");

    noteModal.addEventListener("show.bs.modal", (event) => {
      const button = event.relatedTarget;
      if (!button) return;
      nameLabel.textContent = button.dataset.studentName || "";
      bodyField.value = button.dataset.studentNote || "";
      form.action = button.dataset.noteAction || "";
    });
    noteModal.addEventListener("shown.bs.modal", () => bodyField.focus());
  }
});
