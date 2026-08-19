// 공지 포털 화면 전용 스크립트 - 새 공지 작성/수정 모달을 하나로 재사용한다.
document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("noticeFormModal");
  if (!modal) return;

  const form = modal.querySelector("#noticeForm");
  const heading = modal.querySelector("#noticeFormModalLabel");
  const submitButton = modal.querySelector("#noticeFormSubmit");
  const titleField = modal.querySelector("#noticeTitleInput");
  const contentField = modal.querySelector("#noticeContentInput");
  const publishField = modal.querySelector("#noticePublishInput");

  modal.addEventListener("show.bs.modal", (event) => {
    const button = event.relatedTarget;
    if (!button) return;
    form.action = button.dataset.formAction || "";

    if (button.dataset.mode === "edit") {
      heading.innerHTML = '<i class="bi bi-megaphone-fill me-2 text-primary"></i>공지 수정';
      submitButton.textContent = "저장";
      titleField.value = button.dataset.noticeTitle || "";
      contentField.value = button.dataset.noticeContent || "";
      publishField.checked = button.dataset.noticePublished === "1";
    } else {
      heading.innerHTML = '<i class="bi bi-megaphone-fill me-2 text-primary"></i>새 공지 작성';
      submitButton.textContent = "등록";
      form.reset();
    }
  });
});
