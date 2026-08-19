// 대시보드 상단 공지 바 - 자동 순환, 수동 이동, 상세/목록 모달 연결.
document.addEventListener("DOMContentLoaded", () => {
  const bar = document.getElementById("noticeBar");
  if (!bar) return;

  const items = Array.from(bar.querySelectorAll(".notice-bar-item"));
  const counter = bar.querySelector(".notice-bar-current");
  let index = 0;
  let timer = null;

  const show = (nextIndex) => {
    items[index].classList.add("d-none");
    index = (nextIndex + items.length) % items.length;
    items[index].classList.remove("d-none");
    if (counter) counter.textContent = index + 1;
  };

  const restart = () => {
    if (timer) clearInterval(timer);
    if (items.length > 1) {
      timer = setInterval(() => show(index + 1), Number(bar.dataset.interval) || 3000);
    }
  };

  bar.querySelector(".notice-bar-prev")?.addEventListener("click", () => {
    show(index - 1);
    restart();
  });
  bar.querySelector(".notice-bar-next")?.addEventListener("click", () => {
    show(index + 1);
    restart();
  });

  restart();

  // 상세 모달 - 공지 바 제목 또는 전체 목록 항목에서 넘어온 <template>을 그대로 복제한다.
  const detailModalEl = document.getElementById("noticeDetailModal");
  const detailBody = detailModalEl?.querySelector("#noticeDetailBody");

  const fillDetail = (templateId) => {
    const template = templateId ? document.getElementById(templateId) : null;
    if (!detailBody) return;
    detailBody.innerHTML = "";
    if (template) detailBody.appendChild(template.content.cloneNode(true));
  };

  detailModalEl?.addEventListener("show.bs.modal", (event) => {
    const button = event.relatedTarget;
    if (button?.dataset.noticeTemplate) fillDetail(button.dataset.noticeTemplate);
  });

  // 전체 목록 모달에서 항목을 클릭하면 목록을 닫고 상세 모달을 이어서 연다.
  const listModalEl = document.getElementById("noticeListModal");
  let pendingTemplateId = null;

  listModalEl?.querySelectorAll(".notice-list-item").forEach((item) => {
    item.addEventListener("click", () => {
      pendingTemplateId = item.dataset.noticeTemplate;
      bootstrap.Modal.getOrCreateInstance(listModalEl).hide();
    });
  });

  listModalEl?.addEventListener("hidden.bs.modal", () => {
    if (!pendingTemplateId) return;
    fillDetail(pendingTemplateId);
    pendingTemplateId = null;
    bootstrap.Modal.getOrCreateInstance(detailModalEl).show();
  });
});
