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
    return `<div class="member${isMe ? " me" : ""}${dimmed}${hit}" ${draggableAttributes}><span class="member-initial">${initialLetter}</span><span class="member-name">${displayName}</span>${seed}${myLabel}</div>`;
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
        return `<span class="teams-chip${dimmed}${hit}" ${dragAttributes}>${escapeHtml(person.display_name)}${seed}</span>`;
      })
      .join("");
    // 편집 중에는 비어 있어도 영역을 남긴다 - 팀에서 뺀 학생을 떨어뜨릴 자리가 필요하다.
    if (canEdit) {
      const body = people.length
        ? `<div>${memberChips}</div>`
        : '<p class="teams-waiting-hint">학생을 이곳으로 끌어다 놓으면 팀에서 빠집니다.</p>';
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

  // 저장 뒤 다음 절차 안내 배너. 다시 편집을 시작하면 감춘다 - 저장하지 않은 변경이 있는데
  // "저장했습니다"가 남아 있으면 잘못 읽힌다.
  function showSaveNotice(visible) {
    const notice = byId("saveNotice");
    if (!notice) return;
    const link = byId("saveNoticeLink");
    if (visible && link && config.nextUrl) link.href = config.nextUrl;
    notice.hidden = !visible || !config.nextUrl;
  }

  function renderTutorBoard() {
    const canEdit = !data.is_read_only;
    renderUnassignedMembers(canEdit);
    renderBoard({ canEdit });
    renderSearchMetric();
    byId("cancelButton").disabled = !isDirty;
    // 미배정 인원이 있어도 저장은 할 수 있다 - saveConfiguration이 확인창을 띄운
    // 뒤 재확인 값을 담아 다시 보낸다. 팀이 하나도 없는 등 저장 자체가 불가능한
    // 경우는 서버가 막는다.
    byId("saveButton").disabled = !isDirty;
    if (isDirty) showSaveNotice(false);
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
      renderTutorBoard();
      showSaveNotice(true);
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
    byId("saveButton").addEventListener("click", () => {
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
