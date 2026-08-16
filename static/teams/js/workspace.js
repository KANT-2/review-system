(() => {
  const config = window.TEAMS_PAGE;
  const initialDataElement = document.getElementById("teams-initial-data");
  const initial = JSON.parse(initialDataElement.textContent);
  let data = structuredClone(initial);
  let saved = structuredClone(initial);
  let isDirty = false;

  const byId = (id) => document.getElementById(id);
  const csrfToken = () =>
    document.cookie
      .split("; ")
      .find((item) => item.startsWith("csrftoken="))
      ?.split("=")[1] || "";

  function escapeHtml(value) {
    const element = document.createElement("span");
    element.textContent = String(value);
    return element.innerHTML;
  }

  function layout(teamCount) {
    const rows = [];
    let remaining = teamCount;
    while (remaining > 0) {
      rows.push(Math.min(5, remaining));
      remaining -= 5;
    }
    const widestRow = Math.max(...rows, 1);
    const width = widestRow <= 2 ? 280 : widestRow === 3 ? 270 : widestRow === 4 ? 240 : 220;
    return { rows, width };
  }

  function showEmptyState(status, title, text) {
    byId("toolbar").hidden = true;
    byId("board").hidden = true;
    byId("emptyState").hidden = false;
    byId("statusBadge").textContent = status;
    byId("statusBadge").classList.add("closed");
    byId("emptyTitle").textContent = title;
    byId("emptyText").textContent = text;
  }

  function memberMarkup(person, canEdit) {
    const isMe = person.participant_id === config.myParticipantId;
    const draggableAttributes = canEdit
      ? `draggable="true" data-person="${person.participant_id}"`
      : "";
    const myLabel = isMe ? '<span class="me-tag">나</span>' : "";
    const displayName = escapeHtml(person.display_name);
    const initialLetter = escapeHtml(person.display_name?.[0] || "-");
    return `<div class="member${isMe ? " me" : ""}" ${draggableAttributes}><span class="member-initial">${initialLetter}</span><span>${displayName}</span>${myLabel}</div>`;
  }

  function teamCardMarkup(team, canEdit, showMyTeam) {
    const isMyTeam =
      showMyTeam &&
      team.members.some((person) => person.participant_id === config.myParticipantId);
    const cardLabel = isMyTeam
      ? '<span class="mine-label">나의 팀</span>'
      : `<span>${team.members.length}명</span>`;
    return `<article class="team-card${isMyTeam ? " mine" : ""}" data-team="${team.team_number}"><header><h2>${escapeHtml(team.name)}</h2>${cardLabel}</header><div class="members">${team.members.map((person) => memberMarkup(person, canEdit)).join("")}</div></article>`;
  }

  function renderBoard({ canEdit = false, showMyTeam = false } = {}) {
    const teams = data.teams || [];
    const shape = layout(teams.length);
    let cursor = 0;
    byId("teamRows").innerHTML = shape.rows
      .map((size) => {
        const group = teams.slice(cursor, cursor + size);
        cursor += size;
        return `<div class="teams-row" style="--w:${shape.width}px">${group.map((team) => teamCardMarkup(team, canEdit, showMyTeam)).join("")}</div>`;
      })
      .join("");
    if (canEdit) bindDragEvents();
  }

  function renderUnassignedMembers(canEdit) {
    const people = data.unassigned_members || [];
    const memberChips = people
      .map((person) => {
        const dragAttributes = canEdit
          ? `draggable="true" data-person="${person.participant_id}"`
          : "";
        return `<span class="teams-chip" ${dragAttributes}>${escapeHtml(person.display_name)}</span>`;
      })
      .join("");
    byId("unassignedArea").innerHTML = people.length
      ? `<div class="teams-waiting"><strong>미배정 학생 ${people.length}명</strong><div>${memberChips}</div></div>`
      : "";
    byId("unassignedMetric").textContent = `미배정 ${people.length}명`;
    byId("unassignedMetric").className = `teams-metric ${people.length ? "warn" : "neutral"}`;
  }

  function bindDragEvents() {
    document.querySelectorAll("[data-person]").forEach((item) => {
      item.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", item.dataset.person);
      });
    });
    document.querySelectorAll("[data-team]").forEach((team) => {
      team.addEventListener("dragover", (event) => {
        event.preventDefault();
        team.classList.add("over");
      });
      team.addEventListener("dragleave", () => team.classList.remove("over"));
      team.addEventListener("drop", (event) => {
        event.preventDefault();
        team.classList.remove("over");
        moveParticipant(
          Number(event.dataTransfer.getData("text/plain")),
          Number(team.dataset.team),
        );
      });
    });
  }

  function moveParticipant(participantId, teamNumber) {
    let participant;
    const waiting = data.unassigned_members || [];
    const waitingIndex = waiting.findIndex((item) => item.participant_id === participantId);
    if (waitingIndex >= 0) {
      [participant] = waiting.splice(waitingIndex, 1);
    } else {
      for (const team of data.teams) {
        const index = team.members.findIndex((item) => item.participant_id === participantId);
        if (index >= 0) {
          [participant] = team.members.splice(index, 1);
          break;
        }
      }
    }
    const destination = data.teams.find((team) => team.team_number === teamNumber);
    if (!participant || !destination) return;
    destination.members.push(participant);
    isDirty = true;
    renderTutorBoard();
  }

  function renderTutorBoard() {
    const canEdit = !data.is_read_only;
    renderUnassignedMembers(canEdit);
    renderBoard({ canEdit });
    byId("cancelButton").disabled = !isDirty;
    byId("saveButton").disabled = !isDirty || data.unassigned_members.length > 0;
  }

  function participantCount() {
    return (
      data.teams.reduce((total, team) => total + team.members.length, 0) +
      (data.unassigned_members || []).length
    );
  }

  function configureTeamCountSelect() {
    const currentCount = Math.max(2, data.teams.length || 2);
    const maximumCount = Math.max(2, participantCount());
    byId("teamCount").innerHTML = Array.from(
      { length: maximumCount - 1 },
      (_, index) => index + 2,
    )
      .map(
        (teamCount) =>
          `<option value="${teamCount}" ${teamCount === currentCount ? "selected" : ""}>${teamCount}</option>`,
      )
      .join("");
  }

  async function post(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.error?.message || "요청을 처리하지 못했습니다.");
      error.code = body.error?.code;
      throw error;
    }
    return body;
  }

  function allParticipants() {
    return [...data.teams.flatMap((team) => team.members), ...data.unassigned_members];
  }

  async function createAutomaticAssignment() {
    const teamCount = Number(byId("teamCount").value);
    if (config.previewMode) {
      const people = allParticipants();
      data.teams = Array.from({ length: teamCount }, (_, index) => ({
        team_number: index + 1,
        name: `${index + 1}팀`,
        members: [],
      }));
      people.forEach((person, index) => data.teams[index % teamCount].members.push(person));
      data.unassigned_members = [];
      byId("seedMetric").textContent = "유효 시드 29명";
      byId("balanceMetric").textContent = "팀 균형 편차 8.42 → 3.18";
      isDirty = true;
      renderTutorBoard();
      return;
    }

    const people = allParticipants();
    const result = await post(config.autoUrl, {
      team_count: teamCount,
      lock_version: data.lock_version,
    });
    data.teams = result.teams.map((team) => ({
      ...team,
      members: team.participant_ids
        .map((participantId) =>
          people.find((person) => person.participant_id === participantId),
        )
        .filter(Boolean),
    }));
    data.unassigned_members = [];
    byId("seedMetric").textContent = `유효 시드 ${result.quality.seeded_participant_count}명`;
    const initialDeviation = result.quality.initial_standard_deviation ?? "N/A";
    const finalDeviation = result.quality.final_standard_deviation ?? "N/A";
    byId("balanceMetric").textContent =
      `팀 균형 편차 ${initialDeviation} → ${finalDeviation}`;
    isDirty = true;
    renderTutorBoard();
  }

  function savePayload(imbalanceConfirmed) {
    return {
      lock_version: data.lock_version,
      imbalance_confirmed: imbalanceConfirmed,
      teams: data.teams.map((team) => ({
        team_number: team.team_number,
        name: team.name,
        participant_ids: team.members.map((person) => person.participant_id),
      })),
    };
  }

  async function saveConfiguration(imbalanceConfirmed = false) {
    if (config.previewMode) {
      saved = structuredClone(data);
      isDirty = false;
      renderTutorBoard();
      return;
    }
    try {
      const result = await post(config.saveUrl, savePayload(imbalanceConfirmed));
      data.lock_version = result.lock_version;
      saved = structuredClone(data);
      isDirty = false;
      renderTutorBoard();
    } catch (error) {
      if (
        error.code === "imbalance_confirmation_required" &&
        window.confirm("팀별 인원 차이가 큽니다. 현재 구성으로 저장하시겠습니까?")
      ) {
        await saveConfiguration(true);
        return;
      }
      throw error;
    }
  }

  function showRequestError(error) {
    window.alert(error.message || "요청을 처리하지 못했습니다.");
  }

  if (config.role === "tutor") {
    if (data.round_status !== "DRAFT" && !data.is_configured) {
      showEmptyState(
        "프로젝트 종료",
        "현재 진행 중인 팀 편성이 없습니다",
        "다음 프로젝트가 시작되면 참가자를 확인하고 새 팀 편성을 진행할 수 있습니다.",
      );
      return;
    }

    if (data.is_read_only) {
      byId("toolbar").hidden = true;
      byId("statusBadge").textContent = "편성 완료";
      byId("pageDescription").textContent = "종료된 회차의 팀 구성은 조회만 할 수 있습니다.";
      renderUnassignedMembers(false);
      renderBoard();
      return;
    }

    byId("toolbar").hidden = false;
    byId("statusBadge").textContent = "DRAFT · 편집 가능";
    byId("pageDescription").textContent =
      "자동 배치 결과를 확인하고 필요한 학생만 다른 팀으로 이동하세요.";
    byId("legend").textContent = "학생 이름을 끌어 다른 팀으로 이동할 수 있습니다.";
    configureTeamCountSelect();
    renderTutorBoard();

    byId("cancelButton").addEventListener("click", () => {
      data = structuredClone(saved);
      isDirty = false;
      renderTutorBoard();
    });
    byId("autoButton").addEventListener("click", () => {
      createAutomaticAssignment().catch(showRequestError);
    });
    byId("saveButton").addEventListener("click", () => {
      saveConfiguration().catch(showRequestError);
    });
  } else {
    if (!data.is_configured) {
      showEmptyState(
        "팀 편성 전",
        "현재 배정된 팀이 없습니다",
        "다음 프로젝트 팀 편성이 완료되면 이곳에서 확인할 수 있습니다.",
      );
      return;
    }
    byId("statusBadge").textContent = "팀 편성 완료";
    byId("pageDescription").textContent = "현재 프로젝트의 전체 팀과 나의 팀을 확인하세요.";
    byId("legend").textContent = "";
    renderBoard({ showMyTeam: true });
  }
})();
