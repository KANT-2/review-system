(() => {
  const config = window.TEAMS_PAGE;
  const initialDataElement = document.getElementById("teams-initial-data");
  const initial = JSON.parse(initialDataElement.textContent);
  let data = structuredClone(initial);
  let saved = structuredClone(initial);
  let isDirty = false;
  // 저장 직후에는 저장 버튼이 다음 단계로 이동하는 버튼으로 바뀐다 - 편집을 다시
  // 시작하면(isDirty) 원래 저장 버튼으로 되돌린다.
  let justSaved = false;
  // 드래그가 어려운 환경(터치·키보드·보조기기)에서도 옮길 수 있게 "고르고 → 놓을 곳 누르기"
  // 경로를 함께 둔다. 드래그는 그대로 살아 있다.
  let selectedParticipantId = null;

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

  // 검색은 화면을 떠나지 않고 입력 즉시 걸린다. 찾은 사람만 남기면 어느 팀 소속인지
  // 알 수 없어지므로, 팀 구성은 그대로 두고 매칭되지 않는 사람만 흐리게 처리한다.
  let searchQuery = "";

  function normalize(value) {
    return String(value ?? "").trim().toLowerCase();
  }

  function matchesSearch(person) {
    if (!searchQuery) return true;
    return normalize(person.display_name).includes(searchQuery);
  }

  function seedLabel(person) {
    // 학생 화면 응답에는 seed_scores 자체가 안 내려오므로(개인정보 보호) 튜터 화면에서만 뜬다.
    const score = data.seed_scores?.[person.participant_id];
    return `<span class="member-seed">시드 ${score ?? "-"}</span>`;
  }

  function memberMarkup(person, canEdit) {
    const isMe = person.participant_id === config.myParticipantId;
    const draggableAttributes = canEdit
      ? `draggable="true" data-person="${person.participant_id}"`
      : "";
    const myLabel = isMe ? '<span class="me-tag">나</span>' : "";
    const displayName = escapeHtml(person.display_name);
    const initialLetter = escapeHtml(person.display_name?.[0] || "-");
    const dimmed = matchesSearch(person) ? "" : " dimmed";
    const hit = searchQuery && matchesSearch(person) ? " search-hit" : "";
    const seed = config.role === "tutor" ? seedLabel(person) : "";
    const picked = canEdit && person.participant_id === selectedParticipantId ? " picked" : "";
    // 편집 가능할 때만 버튼처럼 다룬다 - 학생 화면에서는 그냥 이름표다.
    const reachable = canEdit ? 'tabindex="0" role="button"' : "";
    return `<div class="member${isMe ? " me" : ""}${dimmed}${hit}${picked}" ${draggableAttributes} ${reachable}><span class="member-initial">${initialLetter}</span><span class="member-name">${displayName}</span>${seed}${myLabel}</div>`;
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
        const dimmed = matchesSearch(person) ? "" : " dimmed";
        const hit = searchQuery && matchesSearch(person) ? " search-hit" : "";
        const seed = config.role === "tutor" ? seedLabel(person) : "";
        const picked = canEdit && person.participant_id === selectedParticipantId ? " picked" : "";
        const reachable = canEdit ? 'tabindex="0" role="button"' : "";
        return `<span class="teams-chip${dimmed}${hit}${picked}" ${dragAttributes} ${reachable}>${escapeHtml(person.display_name)}${seed}</span>`;
      })
      .join("");
    // 편집 중에는 비어 있어도 영역을 남긴다 - 팀에서 뺀 학생을 떨어뜨릴 자리가 필요하다.
    if (canEdit) {
      const body = people.length
        ? `<div>${memberChips}</div>`
        : '<p class="teams-waiting-hint">학생을 이곳으로 끌어다 놓거나, 학생을 고른 뒤 이곳을 누르면 팀에서 빠집니다.</p>';
      byId("unassignedArea").innerHTML =
        `<div class="teams-waiting${people.length ? "" : " empty"}" data-dropzone="unassigned"><strong>미배정 학생 ${people.length}명</strong>${body}</div>`;
    } else {
      byId("unassignedArea").innerHTML = people.length
        ? `<div class="teams-waiting"><strong>미배정 학생 ${people.length}명</strong><div>${memberChips}</div></div>`
        : "";
    }
    byId("unassignedMetric").textContent = `미배정 ${people.length}명`;
    byId("unassignedMetric").className = `teams-metric ${people.length ? "warn" : "neutral"}`;
  }

  function bindDragEvents() {
    document.querySelectorAll("[data-person]").forEach((item) => {
      item.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", item.dataset.person);
        event.dataTransfer.effectAllowed = "move";
        document.body.classList.add("teams-dragging");
      });
      item.addEventListener("dragend", () => {
        document.body.classList.remove("teams-dragging");
        document
          .querySelectorAll(".over")
          .forEach((element) => element.classList.remove("over"));
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
        // 팀 카드가 처리했으면 아래의 보드 배경 핸들러까지 내려가지 않게 막는다.
        event.stopPropagation();
        team.classList.remove("over");
        moveParticipant(
          Number(event.dataTransfer.getData("text/plain")),
          Number(team.dataset.team),
        );
      });
    });
    bindUnassignDropzones();
    bindClickMoveEvents();
  }

  function selectPerson(participantId) {
    selectedParticipantId = selectedParticipantId === participantId ? null : participantId;
    renderTutorBoard();
  }

  function dropSelectedOn(teamNumber) {
    if (selectedParticipantId === null) return false;
    const participantId = selectedParticipantId;
    selectedParticipantId = null;
    if (teamNumber === null) {
      unassignParticipant(participantId);
    } else {
      moveParticipant(participantId, teamNumber);
    }
    return true;
  }

  function bindClickMoveEvents() {
    document.querySelectorAll("[data-person]").forEach((item) => {
      const participantId = Number(item.dataset.person);
      const activate = (event) => {
        // 이미 고른 학생이 있으면, 다른 학생을 누른 것도 "그 학생이 속한 팀에 놓기"로 읽는다.
        // 카드가 가득 차 빈 자리가 없을 때 옮길 방법이 없던 문제를 없앤다.
        if (selectedParticipantId !== null && selectedParticipantId !== participantId) {
          const card = item.closest("[data-team]");
          event.stopPropagation();
          dropSelectedOn(card ? Number(card.dataset.team) : null);
          return;
        }
        event.stopPropagation();
        selectPerson(participantId);
      };
      item.addEventListener("click", activate);
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate(event);
        }
      });
    });
    document.querySelectorAll("[data-team]").forEach((team) => {
      team.addEventListener("click", () => dropSelectedOn(Number(team.dataset.team)));
    });
    const waiting = byId("unassignedArea")?.querySelector("[data-dropzone]");
    waiting?.addEventListener("click", () => dropSelectedOn(null));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && selectedParticipantId !== null) {
        selectedParticipantId = null;
        renderTutorBoard();
      }
    });
  }

  function bindUnassignDropzones() {
    // 미배정 영역과 보드 여백 - 어느 쪽에 떨어뜨려도 팀에서 빠진다.
    const zones = [byId("unassignedArea").querySelector("[data-dropzone]"), byId("board")];
    zones.filter(Boolean).forEach((zone) => {
      zone.addEventListener("dragover", (event) => {
        event.preventDefault();
        zone.classList.add("over");
      });
      zone.addEventListener("dragleave", () => zone.classList.remove("over"));
      zone.addEventListener("drop", (event) => {
        event.preventDefault();
        zone.classList.remove("over");
        unassignParticipant(Number(event.dataTransfer.getData("text/plain")));
      });
    });
  }

  function unassignParticipant(participantId) {
    // 회차 참가자 명단에서 지우는 게 아니라 팀에서만 뺀다 - 명단 자체는 회차 편집 화면에서 다룬다.
    for (const team of data.teams) {
      const index = team.members.findIndex((item) => item.participant_id === participantId);
      if (index >= 0) {
        const [participant] = team.members.splice(index, 1);
        data.unassigned_members.push(participant);
        isDirty = true;
        renderTutorBoard();
        return;
      }
    }
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

  function renderSearchMetric() {
    const metric = byId("searchMetric");
    if (!metric) return;
    if (!searchQuery) {
      metric.hidden = true;
      return;
    }
    const hits = allParticipants().filter(matchesSearch).length;
    metric.hidden = false;
    metric.textContent = `검색 ${hits}명`;
    metric.className = `teams-metric ${hits ? "neutral" : "warn"}`;
  }

  // 저장 직후에는 저장 버튼 자체를 다음 단계로 이동하는 버튼으로 바꾼다. 다시
  // 편집을 시작하면(isDirty) 원래 저장 버튼으로 되돌린다.
  function renderSaveButton() {
    const button = byId("saveButton");
    if (justSaved && config.nextUrl) {
      button.textContent = "다음 단계: 회차 진행 현황";
      button.disabled = false;
      return;
    }
    button.textContent = "저장";
    // 미배정 인원이 있어도 저장은 할 수 있다 - saveConfiguration이 확인창을 띄운
    // 뒤 재확인 값을 담아 다시 보낸다. 팀이 하나도 없는 등 저장 자체가 불가능한
    // 경우는 서버가 막는다.
    button.disabled = !isDirty;
  }

  function renderTutorBoard() {
    const canEdit = !data.is_read_only;
    renderUnassignedMembers(canEdit);
    renderBoard({ canEdit });
    renderSearchMetric();
    byId("cancelButton").disabled = !isDirty;
    if (isDirty) justSaved = false;
    renderSaveButton();
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
    data.seed_scores = result.seed_scores || {};
    byId("seedMetric").textContent = `유효 시드 ${result.quality.seeded_participant_count}명`;
    const initialDeviation = result.quality.initial_standard_deviation ?? "N/A";
    const finalDeviation = result.quality.final_standard_deviation ?? "N/A";
    byId("balanceMetric").textContent =
      `팀 균형 편차 ${initialDeviation} → ${finalDeviation}`;
    isDirty = true;
    renderTutorBoard();
  }

  function savePayload(imbalanceConfirmed, unassignedConfirmed) {
    return {
      lock_version: data.lock_version,
      imbalance_confirmed: imbalanceConfirmed,
      unassigned_confirmed: unassignedConfirmed,
      teams: data.teams.map((team) => ({
        team_number: team.team_number,
        name: team.name,
        participant_ids: team.members.map((person) => person.participant_id),
      })),
    };
  }

  async function saveConfiguration(imbalanceConfirmed = false, unassignedConfirmed = false) {
    if (config.previewMode) {
      saved = structuredClone(data);
      isDirty = false;
      justSaved = true;
      renderTutorBoard();
      return;
    }
    try {
      const result = await post(
        config.saveUrl,
        savePayload(imbalanceConfirmed, unassignedConfirmed),
      );
      data.lock_version = result.lock_version;
      saved = structuredClone(data);
      isDirty = false;
      justSaved = true;
      renderTutorBoard();
    } catch (error) {
      // 미배정 인원과 인원 불균형은 각자 별도로 확인받는다 - 하나만 확인하고 넘어가면
      // 나머지 경고를 놓칠 수 있어서, 서버가 알려주는 대로 하나씩 다시 확인한다.
      if (
        error.code === "unassigned_confirmation_required" &&
        window.confirm(
          `다음 학생은 팀 없이 저장됩니다: ${data.unassigned_members.map((person) => person.display_name).join(", ")}. ` +
            "이 학생들은 배정 전까지 이번 회차 평가에서 빠집니다. 그래도 지금 저장할까요?",
        )
      ) {
        await saveConfiguration(imbalanceConfirmed, true);
        return;
      }
      if (
        error.code === "imbalance_confirmation_required" &&
        window.confirm("팀별 인원 차이가 큽니다. 현재 구성으로 저장하시겠습니까?")
      ) {
        await saveConfiguration(true, unassignedConfirmed);
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
    byId("legend").textContent =
      "학생 이름을 끌어 다른 팀으로 옮기거나, 미배정 영역·보드 여백에 놓아 팀에서 뺄 수 있습니다.";
    configureTeamCountSelect();
    renderTutorBoard();

    byId("memberSearch").addEventListener("input", (event) => {
      searchQuery = normalize(event.target.value);
      renderTutorBoard();
    });

    byId("cancelButton").addEventListener("click", () => {
      data = structuredClone(saved);
      isDirty = false;
      renderTutorBoard();
    });
    byId("autoButton").addEventListener("click", () => {
      createAutomaticAssignment().catch(showRequestError);
    });
    // 팀 편성은 저장 버튼을 눌러야 서버에 남는다 - 옮겨 놓고 그냥 나가면 전부 사라진다.
    window.addEventListener("beforeunload", (event) => {
      if (!isDirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
    byId("saveButton").addEventListener("click", () => {
      if (justSaved && config.nextUrl) {
        window.location.href = config.nextUrl;
        return;
      }
      saveConfiguration().catch(showRequestError);
    });
  } else {
    if (!data.is_configured) {
      showEmptyState(
        "팀 배정 전",
        "현재 배정된 팀이 없습니다",
        "다음 프로젝트 팀 배정이 완료되면 이곳에서 확인할 수 있습니다.",
      );
      return;
    }
    byId("statusBadge").textContent = "팀 배정 완료";
    byId("pageDescription").textContent = "현재 프로젝트의 전체 팀과 나의 팀을 확인하세요.";
    byId("legend").textContent = "";
    renderBoard({ showMyTeam: true });
  }
})();
