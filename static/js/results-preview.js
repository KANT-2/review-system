// 결과 프로토타입 전용 스크립트.
document.addEventListener("DOMContentLoaded", () => {
  // Django messages를 토스트로 잠깐 띄웠다가 사라지게 한다.
  const toast = document.getElementById("axToast");
  if (toast) {
    requestAnimationFrame(() => toast.classList.add("show"));
    setTimeout(() => toast.classList.remove("show"), 2600);
  }

  // "더보기" 토글 버튼의 문구를 펼침 상태에 맞춰 바꾼다.
  // (아이콘 회전은 app.css의 [aria-expanded="true"] 규칙으로 처리됨)
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

  // 데이터 상태 필터 (전체/일부 제출/미제출) - 카드 안의 표 행을 data-status 기준으로 숨긴다.
  document.querySelectorAll(".ax-filter-group").forEach((group) => {
    const card = group.closest(".ax-card");
    if (!card) return;
    const rows = card.querySelectorAll("tbody tr[data-status]");
    const restBody = card.querySelector("tbody.collapse");

    group.querySelectorAll(".ax-filter-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        group.querySelectorAll(".ax-filter-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        const filter = chip.dataset.filter;

        let hiddenSectionHasMatch = false;
        rows.forEach((row) => {
          const match = filter === "ALL" || row.dataset.status === filter;
          row.classList.toggle("ax-row-hidden", !match);
          if (match && restBody && restBody.contains(row)) {
            hiddenSectionHasMatch = true;
          }
        });

        if (restBody && filter !== "ALL" && hiddenSectionHasMatch) {
          bootstrap.Collapse.getOrCreateInstance(restBody, { toggle: false }).show();
        }
      });
    });
  });

  // 사이드바 접기/펼치기 (세션 동안만 기억 - sessionStorage).
  const sidebar = document.getElementById("axSidebar");
  const collapseBtn = document.getElementById("axSidebarCollapseToggle");
  if (sidebar && collapseBtn) {
    if (sessionStorage.getItem("axSidebarCollapsed") === "1") {
      sidebar.classList.add("ax-sidebar--collapsed");
      collapseBtn.setAttribute("aria-expanded", "false");
    }
    collapseBtn.addEventListener("click", () => {
      const collapsed = sidebar.classList.toggle("ax-sidebar--collapsed");
      collapseBtn.setAttribute("aria-expanded", String(!collapsed));
      sessionStorage.setItem("axSidebarCollapsed", collapsed ? "1" : "0");
    });
  }

  // 점수 계산 비율 안내 등 - hover 시 나오는 툴팁 초기화.
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
    new bootstrap.Tooltip(el);
  });
});
