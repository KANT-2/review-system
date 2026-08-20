// 마이페이지 전용 스크립트 - 5대 역량 레이더차트와 회차별 점수 막대그래프.
// 두 차트 모두 화면 위쪽에 작게 들어가므로 컨테이너 높이를 CSS가 정하고 차트가 따라간다.
document.addEventListener("DOMContentLoaded", () => {
  if (typeof Chart === "undefined") return;

  const rootStyles = getComputedStyle(document.documentElement);
  const textColor = rootStyles.getPropertyValue("--ax-text-muted").trim() || "#667085";
  const textColorStrong = rootStyles.getPropertyValue("--ax-text").trim() || "#333333";
  const gridColor = rootStyles.getPropertyValue("--ax-border").trim() || "#E2E8F0";
  const primaryColor = rootStyles.getPropertyValue("--ax-primary").trim() || "#1769E0";

  const readJson = (id) => {
    const node = document.getElementById(id);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      return null;
    }
  };

  const radarCanvas = document.getElementById("competencyRadarChart");
  const radarData = readJson("competency-radar-data");
  if (radarCanvas && radarData) {
    // 응답 데이터가 없는 역량은 0점이 아니라 "미응답"이므로, 좌표값은 0을 쓰되
    // 점 스타일을 다르게 표시하고 툴팁에서 실제 값처럼 보이지 않게 구분한다.
    const hasScore = radarData.map((entry) => entry.score !== null && entry.score !== undefined);
    new Chart(radarCanvas, {
      type: "radar",
      // 프로필 옆 좁은 자리에 들어가므로 컨테이너 높이에 맞춰 줄어들게 둔다.
      data: {
        labels: radarData.map((entry) => entry.label),
        datasets: [
          {
            label: "역량 점수",
            data: radarData.map((entry) => entry.score ?? 0),
            borderColor: primaryColor,
            backgroundColor: "rgba(23, 105, 224, 0.15)",
            pointBackgroundColor: hasScore.map((has) => (has ? primaryColor : gridColor)),
            pointBorderColor: hasScore.map((has) => (has ? primaryColor : textColor)),
            pointRadius: hasScore.map((has) => (has ? 3 : 4)),
            pointStyle: hasScore.map((has) => (has ? "circle" : "crossRot")),
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          r: {
            min: 0,
            max: 5,
            ticks: { stepSize: 1, backdropColor: "transparent", color: textColor },
            grid: { color: gridColor },
            angleLines: { color: gridColor },
            pointLabels: { color: textColor, font: { size: 11 } },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (context) => {
                const entry = radarData[context.dataIndex];
                return entry.score === null || entry.score === undefined
                  ? "데이터 없음"
                  : `역량 점수: ${entry.score}`;
              },
            },
          },
        },
      },
    });
  }

  const trendWrap = document.getElementById("scoreTrendWrap");
  const trendCanvas = document.getElementById("scoreTrendChart");
  const trendData = readJson("score-trend-data");
  if (trendWrap && trendCanvas && trendData && trendData.length) {
    // 최종 점수를 단일 라인+영역으로 그린다 - 팀/개인/튜터 막대를 나란히 놓고 비교하게
    // 하는 대신, 헤드라인 지표(최종 점수) 하나의 추이를 또렷하게 보여주는 쪽을 택했다.
    // 회차별 팀/개인 점수 자체는 위쪽 통계 카드에서 선택한 회차 기준으로 이미 보여준다.
    const currentRoundId = Number(trendWrap.dataset.currentRoundId) || null;
    const currentIndex = trendData.findIndex((row) => row.round_id === currentRoundId);

    // "4기 평가 11회차" -> "11회차", "[시드] 평가 6회차" -> "6회차 · 시드"
    const shortRoundLabel = (name) => {
      const match = name.match(/(\d+회차)\s*$/);
      const suffix = match ? match[1] : name;
      return name.startsWith("[시드]") ? `${suffix} · 시드` : suffix;
    };

    const ctx = trendCanvas.getContext("2d");
    const areaFill = ctx.createLinearGradient(0, 0, 0, trendCanvas.parentElement.clientHeight || 320);
    areaFill.addColorStop(0, `${primaryColor}26`);
    areaFill.addColorStop(1, `${primaryColor}00`);

    // 커스텀 툴팁 - Chart.js 기본 박스 대신 흰 카드로 그린다.
    let tooltipEl = trendWrap.querySelector(".ax-trend-tooltip");
    if (!tooltipEl) {
      tooltipEl = document.createElement("div");
      tooltipEl.className = "ax-trend-tooltip";
      trendWrap.appendChild(tooltipEl);
    }

    const externalTooltip = (context) => {
      const model = context.tooltip;
      if (!model || model.opacity === 0 || !model.dataPoints || !model.dataPoints.length) {
        tooltipEl.style.opacity = "0";
        return;
      }
      const row = trendData[model.dataPoints[0].dataIndex];
      const parts = [`팀 ${row.team_score_weight}%`, `개인 ${row.personal_score_weight}%`];
      if (row.tutor_score_weight) parts.push(`튜터 ${row.tutor_score_weight}%`);
      const coverageBits = [];
      if (row.team_expected_count) {
        coverageBits.push(`팀 제출 ${row.team_valid_count ?? 0}/${row.team_expected_count}명`);
      }
      if (row.peer_expected_count) {
        coverageBits.push(`개인 제출 ${row.peer_valid_count ?? 0}/${row.peer_expected_count}명`);
      }
      tooltipEl.innerHTML = `
        <div class="ax-trend-tooltip-title">${row.round_name}</div>
        <div class="ax-trend-tooltip-row">최종 점수 ${row.final_score === null ? "N/A" : row.final_score.toFixed(2)}</div>
        <div class="ax-trend-tooltip-sub">${parts.join(" · ")}로 계산</div>
        ${coverageBits.length ? `<div class="ax-trend-tooltip-sub">${coverageBits.join(" · ")}</div>` : ""}
      `;
      tooltipEl.style.opacity = "1";
      tooltipEl.style.left = `${model.caretX}px`;
      tooltipEl.style.top = `${model.caretY}px`;
    };

    new Chart(trendCanvas, {
      type: "line",
      data: {
        labels: trendData.map((row) => shortRoundLabel(row.round_name)),
        datasets: [
          {
            label: "최종 점수",
            data: trendData.map((row) => row.final_score),
            borderColor: primaryColor,
            backgroundColor: areaFill,
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            spanGaps: true,
            pointRadius: (context) => (context.dataIndex === currentIndex ? 6 : 3),
            pointHoverRadius: (context) => (context.dataIndex === currentIndex ? 7 : 5),
            pointBackgroundColor: (context) =>
              context.dataIndex === currentIndex ? primaryColor : "#fff",
            pointBorderColor: primaryColor,
            pointBorderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { min: 0, max: 5, display: false },
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: {
              color: (context) => (context.index === currentIndex ? textColorStrong : textColor),
              font: (context) => ({
                size: 11.5,
                weight: context.index === currentIndex ? "700" : "500",
              }),
            },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false, external: externalTooltip },
        },
      },
    });
  }
});
