// 결과 프로토타입 전용: "더보기" 토글 버튼의 문구를 펼침 상태에 맞춰 바꾼다.
// (아이콘 회전은 app.css의 [aria-expanded="true"] 규칙으로 처리됨)
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".ax-toggle-rest").forEach((button) => {
    const targetId = button.getAttribute("data-bs-target");
    const target = targetId ? document.querySelector(targetId) : null;
    if (!target) return;

    const moreText = button.dataset.moreText;
    const lessText = "접기";

    target.addEventListener("shown.bs.collapse", () => {
      button.querySelector(".ax-toggle-label").textContent = lessText;
    });
    target.addEventListener("hidden.bs.collapse", () => {
      button.querySelector(".ax-toggle-label").textContent = moreText;
    });
  });
});
