(() => {
  const config = window.TEAMS_PAGE;
  const initialDataElement = document.getElementById("teams-initial-data");
  const initial = JSON.parse(initialDataElement.textContent);
  let data = structuredClone(initial);
  let saved = structuredClone(initial);
  let isDirty = false;

  const byId = (id) => document.getElementById(id);
  // CSRF 쿠키는 HttpOnly라 스크립트로 읽을 수 없다 - 서버가 페이지로 내려준 토큰을 쓴다.
  const csrfToken = () =>
    config?.csrfToken ||
    document.cookie
      .split("; ")
      .find((item) => item.startsWith("csrftoken="))
      ?.split("=")[1] ||
    "";

  function escapeHtml(value) {
    const element = document.createElement("span");
    element.textContent = String(value);
    return element.innerHTML;
  }

  function setStatusBadge(text, tone = "pending") {
    const statusBadge = byId("statusBadge");
    statusBadge.textContent = text;
    statusBadge.className = `badge-ax badge-ax-${tone}`;
  }

  function layout(teamCount) {
    if (teamCount <= 0) {
      return { rows: [], width: 280 };
    }
    // 4팀 이하는 한 줄, 5팀부터는 최소 2줄로 나눠서 앞쪽 줄부터 균등하게 채운다.
    // 예: 5팀 -> 3/2, 9팀 -> 5/4, 13팀 -> 5/4/4
    let rows;
    if (teamCount <= 4) {
      rows = [teamCount];
    } else {
      const rowCount = Math.max(2, Math.ceil(teamCount / 5));
      const base = Math.floor(teamCount / rowCount);
      const extra = teamCount % rowCount;
      rows = Array.from({ length: rowCount }, (_, index) => base + (index < extra ? 1 : 0));
    }
    const widestRow = Math.max(...rows, 1);
    const width = widestRow <= 2 ? 280 : widestRow === 3 ? 270 : widestRow === 4 ? 240 : 220;
    return { rows, width };
  }

  function showEmptyState(status, title, text) {
    byId("toolbar").hidden = true;
    byId("board").hidden = true;
    byId("emptyState").hidden = false;
    setStatusBadge(status, "expired");
    byId("emptyTitle").textContent = title;
    byId("emptyText").textContent = text;
  }

  function scoreMarkup(person) {
    if (person.seed_score === null || person.seed_score === undefined) return "";
    return `<span class="member-score">${escapeHtml(person.seed_score)}점</span>`;
  }

  function memberMarkup(person, canEdit, { allowUnassign = false } = {}) {
    const isMe = person.participant_id === config.myParticipantId;
    // data-person은 항상 붙여서(드래그 가능 여부와 무관하게) 버튼 등에서 식별할 수 있게 한다.
    const draggableAttributes = canEdit
      ? `draggable="true" data-person="${person.participant_id}"`
      : `data-person="${person.participant_id}"`;
    const myLabel = isMe ? '<span class="me-tag">나</span>' : "";
    const displayName = escapeHtml(person.display_name);
    const initialLetter = escapeHtml(person.display_name?.[0] || "-");
    const unassignButton =
      canEdit && allowUnassign
        ? `<button type="button" class="member-unassign" data-unassign="${person.participant_id}" title="미배정으로 이동" aria-label="${displayName} 미배정으로 이동">×</button>`
        : "";
    return `<div class="member${isMe ? " me" : ""}" ${draggableAttributes}><span class="member-initial">${initialLetter}</span><span class="member-name">${displayName}</span>${scoreMarkup(person)}${myLabel}${unassignButton}</div>`;
  }

  function teamCardMarkup(team, canEdit, showMyTeam) {
    const isMyTeam =
      showMyTeam &&
      team.members.some((person) => person.participant_id === config.myParticipantId);
    const cardLabel = isMyTeam
      ? '<span class="mine-label">나의 팀</span>'
      : `<span>${team.members.length}명</span>`;
    return `<article class="team-card${isMyTeam ? " mine" : ""}" data-team="${team.team_number}"><header><h2>${escapeHtml(team.name)}</h2>${cardLabel}</header><div class="members">${team.members.map((person) => memberMarkup(person, canEdit, { allowUnassign: true })).join("")}</div></article>`;
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
          : `data-person="${person.participant_id}"`;
        const scoreLabel = scoreMarkup(person);
        return `<span class="teams-chip" ${dragAttributes}>${escapeHtml(person.display_name)}${scoreLabel}</span>`;
      })
      .join("");
    // 편집 가능한 동안에는 미배정 인원이 0명이어도 드롭존을 항상 남겨둬서,
    // 팀에 배치된 학생을 다시 미배정으로 끌어올 수 있는 자리를 유지한다.
    if (!canEdit && people.length === 0) {
      byId("unassignedArea").innerHTML = "";
    } else {
      const heading = people.length
        ? `<strong>미배정 학생 ${people.length}명</strong>`
        : "<strong>미배정 학생 없음</strong>";
      const hint = canEdit
        ? '<p class="teams-waiting-hint">여기로 학생을 끌어오면 미배정으로 이동합니다.</p>'
        : "";
      byId("unassignedArea").innerHTML =
        `<div class="teams-waiting" id="unassignedDropZone">${heading}${hint}<div>${memberChips}</div></div>`;
    }
    byId("unassignedMetric").textContent = `미배정 ${people.length}명`;
    byId("unassignedMetric").className = `teams-metric ${people.length ? "warn" : "neutral"}`;
  }

  function bindDragEvents() {
    document.querySelectorAll("[draggable='true'][data-person]").forEach((item) => {
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
    const dropZone = byId("unassignedDropZone");
    if (dropZone) {
      dropZone.addEventListener("dragover", (event) => {
        event.preventDefault();
        dropZone.classList.add("over");
      });
      dropZone.addEventListener("dragleave", () => dropZone.classList.remove("over"));
      dropZone.addEventListener("drop", (event) => {
        event.preventDefault();
        dropZone.classList.remove("over");
        moveToUnassigned(Number(event.dataTransfer.getData("text/plain")));
      });
    }
    document.querySelectorAll("[data-unassign]").forEach((button) => {
      button.addEventListener("click", () => {
        moveToUnassigned(Number(button.dataset.unassign));
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

  function moveToUnassigned(participantId) {
    // 이미 미배정 상태거나(팀에서 못 찾음) 존재하지 않는 참가자면 아무 것도 하지 않는다.
    let participant;
    for (const team of data.teams) {
      const index = team.members.findIndex((item) => item.participant_id === participantId);
      if (index >= 0) {
        [participant] = team.members.splice(index, 1);
        break;
      }
    }
    if (!participant) return;
    data.unassigned_members = data.unassigned_members || [];
    data.unassigned_members.push(participant);
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
      byId("balanceMetric").textContent = "팀 균형 편차 3.18";
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
    const finalDeviation = result.quality.final_standard_deviation ?? "N/A";
    byId("balanceMetric").textContent = `팀 균형 편차 ${finalDeviation}`;
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
      setStatusBadge("편성 완료", "completed");
      byId("pageDescription").textContent = "종료된 회차의 팀 구성은 조회만 할 수 있습니다.";
      renderUnassignedMembers(false);
      renderBoard();
      return;
    }

    byId("toolbar").hidden = false;
    setStatusBadge("DRAFT · 편집 가능", "pending");
    byId("pageDescription").textContent =
      "자동 배치 결과를 확인하고 필요한 학생만 다른 팀으로 이동하세요.";
    byId("legend").textContent =
      "학생 이름을 끌어 다른 팀이나 미배정 영역으로 이동할 수 있습니다. 팀원 옆의 × 버튼으로도 미배정으로 뺄 수 있습니다.";
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
    setStatusBadge("팀 편성 완료", "completed");
    byId("pageDescription").textContent = "현재 프로젝트의 전체 팀과 나의 팀을 확인하세요.";
    byId("legend").textContent = "";
    renderBoard({ showMyTeam: true });
  }
})();
