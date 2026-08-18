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
});
