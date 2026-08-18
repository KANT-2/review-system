// 마이페이지 전용 스크립트 - 5대 역량 레이더차트와 회차별 점수 추이 막대그래프.
document.addEventListener("DOMContentLoaded", () => {
  if (typeof Chart === "undefined") return;

  const rootStyles = getComputedStyle(document.documentElement);
  const textColor = rootStyles.getPropertyValue("--ax-text-muted").trim() || "#667085";
  const gridColor = rootStyles.getPropertyValue("--ax-border").trim() || "#E2E8F0";
  const primaryColor = rootStyles.getPropertyValue("--ax-primary").trim() || "#1769E0";
  const successColor = rootStyles.getPropertyValue("--ax-success").trim() || "#168A50";

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
    new Chart(radarCanvas, {
      type: "radar",
      data: {
        labels: radarData.map((entry) => entry.label),
        datasets: [
          {
            label: "역량 점수",
            data: radarData.map((entry) => entry.score ?? 0),
            borderColor: primaryColor,
            backgroundColor: "rgba(23, 105, 224, 0.15)",
            pointBackgroundColor: primaryColor,
          },
        ],
      },
      options: {
        scales: {
          r: {
            min: 0,
            max: 5,
            ticks: { stepSize: 1, backdropColor: "transparent", color: textColor },
            grid: { color: gridColor },
            angleLines: { color: gridColor },
            pointLabels: { color: textColor, font: { size: 12 } },
          },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  const trendCanvas = document.getElementById("scoreTrendChart");
  const trendData = readJson("score-trend-data");
  if (trendCanvas && trendData) {
    new Chart(trendCanvas, {
      type: "bar",
      data: {
        labels: trendData.map((row) => row.round_name),
        datasets: [
          {
            label: "팀 점수",
            data: trendData.map((row) => row.team_score),
            backgroundColor: primaryColor,
          },
          {
            label: "개인 점수",
            data: trendData.map((row) => row.peer_score),
            backgroundColor: successColor,
          },
        ],
      },
      options: {
        scales: {
          y: { min: 0, max: 5, ticks: { color: textColor }, grid: { color: gridColor } },
          x: { ticks: { color: textColor }, grid: { display: false } },
        },
        plugins: { legend: { labels: { color: textColor } } },
      },
    });
  }
});
