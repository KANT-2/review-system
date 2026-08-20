// 마이페이지 전용 스크립트 - 5대 역량 레이더차트와 회차별 점수 막대그래프.
// 두 차트 모두 화면 위쪽에 작게 들어가므로 컨테이너 높이를 CSS가 정하고 차트가 따라간다.
document.addEventListener("DOMContentLoaded", () => {
  if (typeof Chart === "undefined") return;

  const rootStyles = getComputedStyle(document.documentElement);
  const textColor = rootStyles.getPropertyValue("--ax-text-muted").trim() || "#667085";
  const gridColor = rootStyles.getPropertyValue("--ax-border").trim() || "#E2E8F0";
  const primaryColor = rootStyles.getPropertyValue("--ax-primary").trim() || "#1769E0";
  const successColor = rootStyles.getPropertyValue("--ax-success").trim() || "#168A50";
  const warningColor = rootStyles.getPropertyValue("--ax-warning").trim() || "#B7791F";
  const infoColor = rootStyles.getPropertyValue("--ax-info").trim() || "#7C3AED";

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

  const trendCanvas = document.getElementById("scoreTrendChart");
  const trendData = readJson("score-trend-data");
  if (trendCanvas && trendData) {
    // 최종 점수는 막대 하나를 더 늘리는 대신 선으로 겹쳐 그린다 - 팀/개인 막대와 헷갈리지
    // 않게 구분하면서도, 헤드라인 지표인 최종 점수의 추이를 함께 볼 수 있게 한다.
    const coverageLabel = (valid, expected) =>
      expected ? ` (${valid ?? 0}/${expected}명 응답)` : "";
    new Chart(trendCanvas, {
      data: {
        labels: trendData.map((row) => row.round_name),
        datasets: [
          {
            type: "bar",
            label: "팀 점수",
            data: trendData.map((row) => row.team_score),
            backgroundColor: primaryColor,
            order: 2,
          },
          {
            type: "bar",
            label: "개인 점수",
            data: trendData.map((row) => row.peer_score),
            backgroundColor: successColor,
            order: 2,
          },
          {
            type: "bar",
            label: "튜터 점수",
            data: trendData.map((row) => row.tutor_score),
            backgroundColor: infoColor,
            order: 2,
          },
          {
            type: "line",
            label: "최종 점수",
            data: trendData.map((row) => row.final_score),
            borderColor: warningColor,
            backgroundColor: warningColor,
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: warningColor,
            tension: 0.25,
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            min: 0,
            max: 5,
            ticks: { color: textColor, stepSize: 1 },
            grid: { color: gridColor },
          },
          x: { ticks: { color: textColor }, grid: { display: false } },
        },
        plugins: {
          legend: { labels: { color: textColor, boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: (context) => {
                const row = trendData[context.dataIndex];
                const label = context.dataset.label;
                if (label === "팀 점수") {
                  return `${label}: ${context.formattedValue}${coverageLabel(row.team_valid_count, row.team_expected_count)}`;
                }
                if (label === "개인 점수") {
                  return `${label}: ${context.formattedValue}${coverageLabel(row.peer_valid_count, row.peer_expected_count)}`;
                }
                if (label === "최종 점수") {
                  const parts = [`팀 ${row.team_score_weight}%`, `개인 ${row.personal_score_weight}%`];
                  if (row.tutor_score_weight) parts.push(`튜터 ${row.tutor_score_weight}%`);
                  return `${label}: ${context.formattedValue} (${parts.join(" · ")}로 계산)`;
                }
                return `${label}: ${context.formattedValue}`;
              },
            },
          },
        },
      },
    });
  }
});
