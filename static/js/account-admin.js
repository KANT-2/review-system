// 수강생 관리 화면 전용 스크립트.
document.addEventListener("DOMContentLoaded", () => {
  // 수강생 공지 메일 - 대상과 발송 시점에 필요한 입력만 활성화한다.
  const announcementForm = document.getElementById("announcement_form");
  if (announcementForm) {
    const targetType = document.getElementById("send_target_type");
    const teamWrapper = document.getElementById("team_select_wrapper");
    const teamSelect = document.getElementById("target_team_id");
    const sendType = document.getElementById("send_type");
    const scheduleWrapper = document.getElementById("schedule_time_wrapper");
    const scheduledAt = document.getElementById("scheduled_at");
    const submitButton = document.getElementById("submit_email_btn");
    const recipientSelectAll = document.getElementById("emailRecipientSelectAll");
    const selectedUsersContainer = document.getElementById("selected_users_container");
    const recipientBoxes = () => document.querySelectorAll(".student-user-checkbox");
    const selectedRecipientBoxes = () =>
      document.querySelectorAll(".student-user-checkbox:checked");

    const syncSelectedUsers = () => {
      selectedUsersContainer.replaceChildren();
      if (targetType.value !== "select") return;

      selectedRecipientBoxes().forEach((box) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "selected_user_ids";
        input.value = box.value;
        selectedUsersContainer.appendChild(input);
      });
    };

    const refreshRecipientSelection = () => {
      const selected = selectedRecipientBoxes().length;
      const total = recipientBoxes().length;
      if (recipientSelectAll) {
        recipientSelectAll.checked = total > 0 && selected === total;
        recipientSelectAll.indeterminate = selected > 0 && selected < total;
      }
      syncSelectedUsers();
    };

    const refreshTargetFields = () => {
      const isTeam = targetType.value === "team";
      teamWrapper.classList.toggle("d-none", !isTeam);
      teamSelect.required = isTeam;
      if (!isTeam) teamSelect.value = "";
      syncSelectedUsers();
    };

    const refreshScheduleFields = () => {
      const isScheduled = sendType.value === "scheduled";
      scheduleWrapper.classList.toggle("d-none", !isScheduled);
      scheduledAt.required = isScheduled;
      if (!isScheduled) scheduledAt.value = "";
      submitButton.textContent = isScheduled ? "공지 메일 예약하기" : "공지 메일 보내기";
    };

    targetType.addEventListener("change", refreshTargetFields);
    sendType.addEventListener("change", refreshScheduleFields);
    recipientSelectAll?.addEventListener("change", () => {
      recipientBoxes().forEach((box) => {
        box.checked = recipientSelectAll.checked;
      });
      refreshRecipientSelection();
    });
    document.addEventListener("change", (event) => {
      if (event.target.classList.contains("student-user-checkbox")) {
        refreshRecipientSelection();
      }
    });

    announcementForm.addEventListener("submit", (event) => {
      syncSelectedUsers();
      if (targetType.value === "select" && selectedRecipientBoxes().length === 0) {
        window.alert("발송할 수강생을 목록에서 한 명 이상 선택해 주세요.");
        event.preventDefault();
      }
    });

    refreshTargetFields();
    refreshScheduleFields();
    refreshRecipientSelection();
  }

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

  // 메모 남기기 모달 - 클릭한 학생의 이름/저장 주소를 폼에 채워 넣는다. 메모는 항상
  // 새 기록으로 추가되므로 입력창은 매번 비워서 연다.
  const noteModal = document.getElementById("studentNoteModal");
  if (noteModal) {
    const form = noteModal.querySelector("#studentNoteForm");
    const nameLabel = noteModal.querySelector("#noteStudentName");
    const bodyField = noteModal.querySelector("#noteBody");

    noteModal.addEventListener("show.bs.modal", (event) => {
      const button = event.relatedTarget;
      if (!button) return;
      nameLabel.textContent = button.dataset.studentName || "";
      bodyField.value = "";
      form.action = button.dataset.noteAction || "";
    });
    noteModal.addEventListener("shown.bs.modal", () => bodyField.focus());
  }

  // 메모 확인 모달 - 클릭한 학생 행에 서버가 미리 렌더링해 둔 <template>(삭제 폼
  // 포함, 실제 CSRF 토큰 포함)을 그대로 복제해 넣는다. JSON을 거치지 않으니 삭제
  // 버튼이 진짜 폼 제출로 동작한다.
  const noteHistoryModal = document.getElementById("studentNoteHistoryModal");
  if (noteHistoryModal) {
    const nameLabel = noteHistoryModal.querySelector("#noteHistoryStudentName");
    const list = noteHistoryModal.querySelector("#noteHistoryList");

    noteHistoryModal.addEventListener("show.bs.modal", (event) => {
      const button = event.relatedTarget;
      if (!button) return;
      nameLabel.textContent = button.dataset.studentName || "";
      const templateId = button.dataset.historyTemplate;
      const template = templateId ? document.getElementById(templateId) : null;
      list.innerHTML = "";
      if (template) {
        list.appendChild(template.content.cloneNode(true));
      }
    });
  }
});
