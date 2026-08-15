(() => {
  const config = window.TEAMS_PAGE;
  const initial = JSON.parse(document.getElementById("teams-initial-data").textContent);
  let data = structuredClone(initial);
  let saved = structuredClone(initial);
  let dirty = false;
  const byId = (id) => document.getElementById(id);
  const csrfToken = () => document.cookie.split("; ").find((item) => item.startsWith("csrftoken="))?.split("=")[1] || "";

  function layout(count) {
    if (count <= 5) return { rows: [count], width: count <= 2 ? 280 : count === 3 ? 270 : count === 4 ? 240 : 220 };
    if (count === 6) return { rows: [3, 3], width: 270 };
    if (count === 7) return { rows: [4, 3], width: 240 };
    if (count === 8) return { rows: [4, 4], width: 240 };
    if (count === 9) return { rows: [5, 4], width: 220 };
    return { rows: [5, 5], width: 220 };
  }
  function empty(title, text) {
    byId("toolbar").hidden = true; byId("board").hidden = true; byId("emptyState").hidden = false;
    byId("statusBadge").textContent = "프로젝트 종료"; byId("statusBadge").classList.add("closed");
    byId("emptyTitle").textContent = title; byId("emptyText").textContent = text;
  }
  function member(person, draggable) {
    const me = person.participant_id === config.myParticipantId;
    return `<div class="member${me ? " me" : ""}" ${draggable ? `draggable="true" data-person="${person.participant_id}"` : ""}><span class="member-initial">${person.display_name[0]}</span><span>${person.display_name}</span>${me ? '<span class="me-tag">나</span>' : ""}</div>`;
  }
  function card(team, tutor) {
    const mine = !tutor && team.members.some((person) => person.participant_id === config.myParticipantId);
    return `<article class="team-card${mine ? " mine" : ""}" data-team="${team.team_number}"><header><h2>${team.name}</h2>${mine ? '<span class="mine-label">나의 팀</span>' : `<span>${team.members.length}명</span>`}</header><div class="members">${team.members.map((person) => member(person, tutor)).join("")}</div></article>`;
  }
  function renderBoard(tutor) {
    const teams = data.teams || []; const shape = layout(teams.length); let cursor = 0;
    byId("teamRows").innerHTML = shape.rows.map((size) => { const group = teams.slice(cursor, cursor + size); cursor += size; return `<div class="teams-row" style="--w:${shape.width}px">${group.map((team) => card(team, tutor)).join("")}</div>`; }).join("");
    if (tutor) bindDrag();
  }
  function renderWaiting() {
    const people = data.unassigned_members || [];
    byId("unassignedArea").innerHTML = people.length ? `<div class="teams-waiting"><strong>미배정 학생 ${people.length}명</strong><div>${people.map((person) => `<span class="teams-chip" draggable="true" data-person="${person.participant_id}">${person.display_name}</span>`).join("")}</div></div>` : "";
    byId("unassignedMetric").textContent = `미배정 ${people.length}명`; byId("unassignedMetric").className = `teams-metric ${people.length ? "warn" : "neutral"}`;
  }
  function bindDrag() {
    document.querySelectorAll("[data-person]").forEach((item) => item.addEventListener("dragstart", (event) => event.dataTransfer.setData("text/plain", item.dataset.person)));
    document.querySelectorAll("[data-team]").forEach((team) => { team.addEventListener("dragover", (event) => { event.preventDefault(); team.classList.add("over"); }); team.addEventListener("dragleave", () => team.classList.remove("over")); team.addEventListener("drop", (event) => { event.preventDefault(); team.classList.remove("over"); move(Number(event.dataTransfer.getData("text/plain")), Number(team.dataset.team)); }); });
  }
  function move(personId, teamNumber) {
    let person; const waiting = data.unassigned_members || []; const waitingIndex = waiting.findIndex((item) => item.participant_id === personId);
    if (waitingIndex >= 0) [person] = waiting.splice(waitingIndex, 1); else for (const team of data.teams) { const index = team.members.findIndex((item) => item.participant_id === personId); if (index >= 0) { [person] = team.members.splice(index, 1); break; } }
    if (!person) return; data.teams.find((team) => team.team_number === teamNumber).members.push(person); dirty = true; renderTutor();
  }
  function renderTutor() {
    renderWaiting(); renderBoard(true); byId("cancelButton").disabled = !dirty; byId("saveButton").disabled = !dirty || data.unassigned_members.length > 0;
  }
  async function post(url, payload) { const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() }, body: JSON.stringify(payload) }); const body = await response.json(); if (!response.ok) throw new Error(body.error?.message || "요청을 처리하지 못했습니다."); return body; }
  if (config.role === "tutor") {
    if (data.round_status !== "DRAFT" && !data.is_configured) { empty("현재 진행 중인 팀 편성이 없습니다", "다음 프로젝트가 시작되면 참가자를 확인하고 새 팀 편성을 진행할 수 있습니다."); return; }
    byId("toolbar").hidden = false; byId("statusBadge").textContent = data.is_read_only ? "편성 완료" : "DRAFT · 편집 가능"; byId("pageDescription").textContent = "자동 배치 결과를 확인하고 필요한 학생만 다른 팀으로 이동하세요."; byId("legend").textContent = "학생 이름을 끌어 다른 팀으로 이동할 수 있습니다.";
    const count = Math.max(2, data.teams.length || 2); byId("teamCount").innerHTML = Array.from({ length: 9 }, (_, i) => `<option ${i + 2 === count ? "selected" : ""}>${i + 2}</option>`).join(""); renderTutor();
    byId("cancelButton").addEventListener("click", () => { data = structuredClone(saved); dirty = false; renderTutor(); });
    byId("autoButton").addEventListener("click", async () => { const result = await post(config.autoUrl, { team_count: Number(byId("teamCount").value), lock_version: data.lock_version }); const people = [...data.teams.flatMap((team) => team.members), ...data.unassigned_members]; data.teams = result.teams.map((team) => ({ ...team, members: team.participant_ids.map((id) => people.find((person) => person.participant_id === id)).filter(Boolean) })); data.unassigned_members = []; byId("seedMetric").textContent = `유효 시드 ${result.quality.seeded_participant_count}명`; byId("balanceMetric").textContent = `팀 균형 편차 ${result.quality.final_standard_deviation ?? "N/A"}`; dirty = true; renderTutor(); });
    byId("saveButton").addEventListener("click", async () => { const result = await post(config.saveUrl, { lock_version: data.lock_version, teams: data.teams.map((team) => ({ team_number: team.team_number, name: team.name, participant_ids: team.members.map((person) => person.participant_id) })) }); data.lock_version = result.lock_version; saved = structuredClone(data); dirty = false; renderTutor(); });
  } else {
    if (!data.is_configured) { empty("현재 배정된 팀이 없습니다", "다음 프로젝트 팀 편성이 완료되면 이곳에서 확인할 수 있습니다."); return; }
    byId("statusBadge").textContent = "팀 편성 완료"; byId("pageDescription").textContent = "현재 프로젝트의 전체 팀과 나의 팀을 확인하세요."; byId("legend").textContent = ""; renderBoard(false);
  }
})();
