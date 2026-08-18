// 수강생 관리 화면 전용 스크립트.
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

  // 승인 대기 목록 - 체크한 계정만 한 번에 승인/반려한다.
  // 되돌릴 수 없는 처리라 제출 직전에 몇 명인지 다시 확인시킨다.
  const bulkForm = document.getElementById("bulkApprovalForm");
  if (bulkForm) {
    const selectAll = document.getElementById("pendingSelectAll");
    const counter = document.getElementById("pendingSelectedCount");
    const actionButtons = bulkForm.querySelectorAll(".ax-bulk-approval");
    const checkboxes = () => bulkForm.querySelectorAll(".ax-pending-check");
    const checkedBoxes = () => bulkForm.querySelectorAll(".ax-pending-check:checked");

    const refresh = () => {
      const selected = checkedBoxes().length;
      const total = checkboxes().length;
      if (counter) {
        counter.textContent = selected
          ? `${selected}명 선택함`
          : "선택한 계정이 없습니다.";
      }
      actionButtons.forEach((button) => {
        button.disabled = selected === 0;
      });
      if (selectAll) {
        selectAll.checked = total > 0 && selected === total;
        selectAll.indeterminate = selected > 0 && selected < total;
      }
    };

    selectAll?.addEventListener("change", () => {
      checkboxes().forEach((box) => {
        box.checked = selectAll.checked;
      });
      refresh();
    });
    bulkForm.addEventListener("change", (event) => {
      if (event.target.classList.contains("ax-pending-check")) refresh();
    });

    actionButtons.forEach((button) => {
      button.addEventListener("click", (event) => {
        const selected = checkedBoxes().length;
        if (!selected) {
          event.preventDefault();
          return;
        }
        const label = button.value === "approve" ? "승인" : "반려";
        const question =
          button.value === "approve"
            ? `${selected}명을 승인합니다. 승인하면 바로 로그인할 수 있습니다. 계속할까요?`
            : `${selected}명을 반려합니다. 반려한 계정은 로그인할 수 없습니다. 계속할까요?`;
        if (!window.confirm(`[${label}] ${question}`)) event.preventDefault();
      });
    });

    refresh();
  }

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
