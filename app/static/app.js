function showToast(message, kind) {
  if (!message) return;
  const region = document.getElementById("toasts");
  const toast = document.createElement("div");
  toast.className = "toast " + (kind || "info");
  toast.textContent = message;
  region.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function readNotice() {
  const params = new URLSearchParams(location.search);
  const notice = params.get("notice");
  if (!notice) return;
  showToast(notice, params.get("kind") || "info");
  params.delete("notice");
  params.delete("kind");
  const next = params.toString();
  history.replaceState({}, "", location.pathname + (next ? "?" + next : ""));
}

function bindTheme() {
  const button = document.getElementById("theme-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    const dark = document.documentElement.classList.toggle("dark");
    localStorage.setItem("lifevault-theme", dark ? "dark" : "light");
  });
}

function bindConfirm() {
  const dialog = document.getElementById("confirm-dialog");
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "1") return;
      event.preventDefault();
      dialog.querySelector("#confirm-title").textContent = form.dataset.confirmTitle || "Remove this mailbox?";
      dialog.querySelector("#confirm-text").textContent = form.dataset.confirmText || "Messages stored for it, and findings that only came from it, will be deleted on this computer.";
      dialog.querySelector("#confirm-ok").textContent = form.dataset.confirmOk || "Remove";
      dialog.showModal();
      dialog.addEventListener("close", () => {
        if (dialog.returnValue === "ok") {
          form.dataset.confirmed = "1";
          form.submit();
        }
      }, { once: true });
    });
  });
}

function pollRun(id) {
  const box = document.getElementById("progress");
  if (!box) return;
  box.hidden = false;
  const stop = document.getElementById("stop-form");
  if (stop) stop.action = "/scans/" + id + "/stop";
  fetch("/scans/" + id + ".json")
    .then((response) => response.json())
    .then((data) => {
      document.getElementById("progress-note").textContent = data.note || data.status;
      const ratio = data.token_budget ? Math.min(100, Math.round((data.tokens_used / data.token_budget) * 100)) : 0;
      document.getElementById("progress-fill").style.width = ratio + "%";
      document.getElementById("progress-meta").textContent =
        data.messages_seen + " read · " + data.messages_screened + " screened · " + data.tokens_used + " / " + data.token_budget + " tokens";
      if (data.status === "running" || data.status === "queued" || data.status === "stopping") {
        setTimeout(() => pollRun(id), 1500);
        return;
      }
      if (data.status === "done") {
        location.href = "/?notice=" + encodeURIComponent(data.note || "Scan finished") + "&kind=success";
        return;
      }
      else if (data.status === "error") showToast(data.error || "Scan failed", "error");
      else if (data.status === "stopped") showToast("Scan stopped", "info");
    })
    .catch(() => showToast("Could not read scan progress", "error"));
}

function currentView() {
  return new URLSearchParams(location.search).get("status") || "active";
}

function findingLeavesView(status) {
  const view = currentView();
  if (view === "all") return false;
  if (view === "active") return status === "dismissed";
  return status !== view;
}

function setCount(name, value) {
  document.querySelectorAll("[data-count='" + name + "']").forEach((node) => {
    node.textContent = String(value);
  });
}

function iconLink(label, href, kind) {
  const link = document.createElement("a");
  link.className = "btn icon";
  link.href = href;
  link.setAttribute("aria-label", label);
  link.title = label;
  const paths = {
    view: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12"/><circle cx="12" cy="12" r="3"/>',
    download: '<path d="M12 4v10M8 10l4 4 4-4M5 19h14"/>',
    print: '<path d="M6 9V3h12v6"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v7H6z"/>',
  };
  link.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + paths[kind] + "</svg>";
  return link;
}

function iconButton(label, kind) {
  const button = document.createElement("button");
  button.type = kind === "confirm" ? "button" : "submit";
  button.className = "btn icon" + (kind === "confirm" ? " primary" : kind === "dismiss" ? " danger" : "");
  button.setAttribute("aria-label", label);
  button.title = label;
  const paths = {
    confirm: '<path d="M5 12.5 9.5 17 19 7"/>',
    dismiss: '<path d="M7 7l10 10M17 7 7 17"/>',
    restore: '<path d="M4 12a8 8 0 1 0 2.3-5.7M4 4v5h5"/>',
  };
  button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + paths[kind] + "</svg>";
  return button;
}

function paintActions(card, status) {
  const row = card.querySelector("[data-actions]");
  const id = card.dataset.finding;
  const back = currentView();
  row.replaceChildren();
  if (status === "discovered" || status === "candidate") {
    const button = iconButton("Identify", "confirm");
    button.addEventListener("click", () => openStepDialog(card));
    row.appendChild(button);
  }
  const form = document.createElement("form");
  form.method = "post";
  form.action = "/findings/" + id + "/status";
  const dismissed = status === "dismissed";
  form.innerHTML = '<input type="hidden" name="status" value="' + (dismissed ? "candidate" : "dismissed") + '"><input type="hidden" name="back" value="' + back + '">';
  const button = iconButton(dismissed ? "Restore" : "Dismiss", dismissed ? "restore" : "dismiss");
  form.appendChild(button);
  form.addEventListener("submit", onFindingSubmit);
  row.appendChild(form);
}

function estateActions() {
  const node = document.getElementById("estate-actions");
  if (!node) return {};
  try {
    return JSON.parse(node.textContent || "{}");
  } catch (error) {
    return {};
  }
}

function stepChoice(value) {
  const row = document.createElement("div");
  row.className = "step-choice";
  row.dataset.action = value;
  const label = document.createElement("label");
  const box = document.createElement("input");
  box.type = "checkbox";
  box.name = "action";
  box.value = value;
  const text = document.createElement("span");
  text.className = "step-text";
  text.textContent = value;
  label.append(box, text);
  const status = document.createElement("span");
  status.className = "step-status";
  row.append(label, status);
  return row;
}

function customStepRow() {
  const row = document.createElement("div");
  row.className = "step-choice";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.className = "js-custom-check";
  box.setAttribute("aria-label", "Select this step");
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Your own step";
  input.addEventListener("input", () => {
    const rows = document.querySelectorAll("#step-custom .step-choice");
    if (row === rows[rows.length - 1] && input.value.trim()) customStepRow();
  });
  row.append(box, input);
  document.getElementById("step-custom").appendChild(row);
  return row;
}

function openStepDialog(card) {
  const dialog = document.getElementById("step-dialog");
  const options = estateActions()[card.dataset.category] || estateActions().other || [];
  document.getElementById("step-title").textContent = card.dataset.status === "confirmed" ? "Add a step" : "Next step";
  document.getElementById("step-asset").textContent = card.querySelector("strong").textContent;
  const list = document.getElementById("step-options");
  list.replaceChildren();
  options.forEach((action) => list.appendChild(stepChoice(action)));
  document.getElementById("step-custom").replaceChildren();
  customStepRow();
  dialog.dataset.finding = card.dataset.finding;
  dialog.showModal();
  watchStepJobs(card.dataset.finding);
}

let stepPoll = 0;

function paintChoiceStatus(row, jobs) {
  const slot = row.querySelector(".step-status");
  if (!slot) return;
  slot.replaceChildren();
  if (!jobs.length) return;
  const job = jobs[jobs.length - 1];
  const pill = document.createElement("span");
  pill.className = "pill status-" + job.status;
  pill.textContent = job.status;
  slot.appendChild(pill);
  if (job.ready) {
    slot.appendChild(iconLink("View", "/documents/" + job.id, "view"));
    slot.appendChild(iconLink("Print", "/documents/" + job.id + "?print=1", "print"));
  }
}

function paintStepStatuses(jobs) {
  const options = document.getElementById("step-options");
  const custom = document.getElementById("step-custom");
  if (!options || !custom) return;
  const known = new Set();
  options.querySelectorAll(".step-choice").forEach((row) => {
    if (!row.dataset.action) return;
    known.add(row.dataset.action);
    paintChoiceStatus(row, jobs.filter((job) => job.action === row.dataset.action));
  });
  custom.querySelectorAll(".js-queued-custom").forEach((row) => row.remove());
  jobs.filter((job) => job.action && !known.has(job.action)).forEach((job) => {
    const row = document.createElement("div");
    row.className = "step-choice js-queued-custom";
    row.dataset.action = job.action;
    const text = document.createElement("span");
    text.className = "step-text";
    text.textContent = job.action;
    const status = document.createElement("span");
    status.className = "step-status";
    row.append(text, status);
    paintChoiceStatus(row, [job]);
    custom.prepend(row);
  });
}

function watchStepJobs(findingId) {
  clearTimeout(stepPoll);
  const tick = () => {
    const dialog = document.getElementById("step-dialog");
    if (!dialog || !dialog.open) return;
    fetch("/queue.json")
      .then((response) => response.json())
      .then((data) => {
        if (!dialog.open || dialog.dataset.finding !== String(findingId)) return;
        const jobs = (data.jobs || []).filter((job) => String(job.finding_id) === String(findingId));
        paintStepStatuses(jobs);
        const active = jobs.some((job) => job.status === "queued" || job.status === "running");
        if (active) stepPoll = setTimeout(tick, 1500);
      })
      .catch(() => {});
  };
  tick();
}

function paintQueue(jobs) {
  const list = document.getElementById("queue-list");
  if (!list) return;
  list.replaceChildren();
  if (!jobs.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "Confirmed steps appear here and run in the background.";
    list.appendChild(empty);
    return;
  }
  jobs.forEach((job) => {
    const item = document.createElement("li");
    item.dataset.job = String(job.id);
    const title = document.createElement("strong");
    title.textContent = job.filename || job.label;
    const detail = document.createElement("p");
    detail.className = "muted";
    detail.textContent = [job.provider, job.action].filter(Boolean).join(" · ");
    const text = document.createElement("div");
    text.append(title, detail);
    const pill = document.createElement("span");
    if (job.ready) {
      const received = job.reply_status === "received";
      pill.className = "pill status-" + (received ? "received" : "awaiting");
      pill.textContent = received ? "Response received" : "Awaiting response";
    } else {
      pill.className = "pill status-" + job.status;
      pill.textContent = job.status;
    }
    item.append(text, pill);
    if (job.ready) {
      item.appendChild(iconLink("View", "/documents/" + job.id, "view"));
      item.appendChild(iconLink("Print", "/documents/" + job.id + "?print=1", "print"));
      item.appendChild(iconLink("Download", "/queue/" + job.id + "/packet", "download"));
    }
    list.appendChild(item);
  });
}

function pollQueue() {
  if (!document.getElementById("queue-list")) return;
  fetch("/queue.json")
    .then((response) => response.json())
    .then((data) => {
      paintQueue(data.jobs || []);
      const active = (data.jobs || []).some((job) => job.status === "queued" || job.status === "running");
      if (active) setTimeout(pollQueue, 1500);
    })
    .catch(() => {});
}

function bindStepDialog() {
  const dialog = document.getElementById("step-dialog");
  const form = document.getElementById("step-form");
  if (!dialog || !form) return;
  document.getElementById("step-cancel").addEventListener("click", () => dialog.close());
  document.getElementById("step-close").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const card = document.querySelector('.asset[data-finding="' + dialog.dataset.finding + '"]');
    document.querySelectorAll("#step-custom .step-choice").forEach((row) => {
      const input = row.querySelector("input[type='text']");
      const box = row.querySelector(".js-custom-check");
      if (!input || !box) return;
      input.removeAttribute("name");
      if (box.checked && input.value.trim()) {
        input.name = "note";
      }
    });
    const body = new FormData(form);
    fetch("/findings/" + dialog.dataset.finding + "/queue", { method: "POST", body: body })
      .then((response) => {
        if (!response.ok) throw new Error("queue");
        return response.json();
      })
      .then((data) => {
        if (card) {
          card.dataset.status = data.status || "processing";
          const pill = card.querySelector(".js-status");
          if (pill) {
            pill.className = "pill js-status status-" + card.dataset.status;
            pill.textContent = card.dataset.status;
          }
          paintActions(card, card.dataset.status);
          document.getElementById("step-title").textContent = "Add a step";
          if (data.counts) {
            ["candidate", "confirmed", "dismissed", "active", "all", "discovered", "identified", "secured", "processing", "closed", "open", "in_process"].forEach((key) => {
              if (data.counts[key] !== undefined) setCount(key, data.counts[key]);
            });
          }
        }
        document.querySelectorAll("#step-options input").forEach((box) => {
          box.checked = false;
        });
        document.getElementById("step-custom").replaceChildren();
        customStepRow();
        watchStepJobs(dialog.dataset.finding);
        showToast("Queued", "success");
        pollQueue();
      })
      .catch(() => showToast("Could not queue that step", "error"));
  });
}

function onFindingSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const card = form.closest(".asset");
  const button = form.querySelector("button");
  if (button) button.disabled = true;
  fetch(form.action, {
    method: "POST",
    body: new FormData(form),
    headers: { "X-Requested-With": "fetch" },
  })
    .then((response) => {
      if (!response.ok) throw new Error("status");
      return response.json();
    })
    .then((data) => {
      const status = data.status;
      card.dataset.status = status;
      const pill = card.querySelector(".js-status");
      if (pill) {
        pill.className = "pill js-status status-" + status;
        pill.textContent = status;
      }
      if (data.counts) {
        ["candidate", "confirmed", "dismissed", "active", "all", "discovered", "identified", "secured", "processing", "closed", "open", "in_process"].forEach((key) => {
          if (data.counts[key] !== undefined) setCount(key, data.counts[key]);
        });
      }
      if (findingLeavesView(status)) {
        const section = card.closest("section.panel");
        const category = card.dataset.category;
        card.remove();
        const viewCount = document.querySelector("[data-count='view']");
        if (viewCount) viewCount.textContent = String(Math.max(0, Number(viewCount.textContent) - 1));
        if (category === "risks") {
          const risks = document.querySelector("[data-count='risks']");
          if (risks) risks.textContent = String(Math.max(0, Number(risks.textContent) - 1));
        }
        const tile = document.querySelector("[data-tile='" + category + "']");
        if (tile) {
          const next = Math.max(0, Number(tile.textContent) - 1);
          tile.textContent = String(next);
          tile.closest(".tile").classList.toggle("empty", next === 0);
        }
        const list = section && section.querySelector(".assets");
        const headingCount = section && section.querySelector(".js-section-count");
        if (headingCount && list) headingCount.textContent = String(list.children.length);
        if (list && list.children.length === 0) section.remove();
      } else {
        paintActions(card, status);
      }
      const note = status === "dismissed" ? "Dismissed" : status === "confirmed" ? "Confirmed" : "Restored";
      showToast(note, "success");
    })
    .catch(() => {
      if (button) button.disabled = false;
      showToast("Could not update that item", "error");
    });
}

function bindFindingActions() {
  document.querySelectorAll(".asset").forEach((card) => paintActions(card, card.dataset.status));
}

function bindAssetCards() {
  document.querySelectorAll(".asset").forEach((card) => {
    card.addEventListener("click", (event) => {
      if (event.target.closest("button, a, input, select, form")) return;
      location.href = "/cases/" + card.dataset.finding;
    });
  });
}

function fillMessageDialog(messages) {
  const box = document.getElementById("message-body");
  box.replaceChildren();
  messages.forEach((message) => {
    const card = document.createElement("article");
    card.className = "message-card";
    const meta = document.createElement("p");
    meta.className = "muted";
    meta.textContent = [message.date, message.from, message.to].filter(Boolean).join(" · ");
    const subject = document.createElement("strong");
    subject.textContent = message.subject || "Message";
    const body = document.createElement("p");
    body.textContent = message.body || "The message text is not stored on this computer.";
    card.append(meta, subject, body);
    box.appendChild(card);
  });
}

function bindKickerBack() {
  document.querySelectorAll("[data-back]").forEach((link) => {
    const ref = document.referrer || "";
    if (!ref.startsWith(location.origin) || ref === location.href) return;
    link.textContent = "Back";
    link.href = ref;
  });
}

function bindSourceMessages() {
  const dialog = document.getElementById("message-dialog");
  if (!dialog) return;
  document.querySelectorAll("[data-source]").forEach((button) => {
    button.addEventListener("click", () => {
      const box = document.getElementById("message-body");
      box.textContent = "Loading the message…";
      dialog.showModal();
      fetch("/findings/" + button.dataset.source + "/messages")
        .then((response) => {
          if (!response.ok) throw new Error("missing");
          return response.json();
        })
        .then((data) => fillMessageDialog(data.messages || []))
        .catch(() => {
          dialog.close();
          showToast("Could not open the source message", "error");
        });
    });
  });
}

function paintGuide(payload, findingId) {
  const body = document.getElementById("guide-body");
  const refresh = document.getElementById("guide-refresh");
  body.replaceChildren();
  refresh.hidden = !payload.has_key;
  if (!payload.has_key) {
    const note = document.createElement("p");
    note.textContent = "Add an OpenAI API key in Settings to prepare close instructions.";
    const link = document.createElement("a");
    link.className = "btn";
    link.href = "/settings";
    link.textContent = "Open Settings";
    body.append(note, link);
    return;
  }
  const guide = payload.guide;
  if (!guide || !guide.steps || !guide.steps.length) {
    const note = document.createElement("p");
    note.textContent = "No close instructions yet. Search again to look up the current path.";
    body.appendChild(note);
    return;
  }
  if (guide.summary) {
    const summary = document.createElement("p");
    summary.textContent = guide.summary;
    body.appendChild(summary);
  }
  const list = document.createElement("ol");
  list.className = "guide-steps";
  guide.steps.forEach((step, index) => {
    const item = document.createElement("li");
    const number = document.createElement("span");
    number.className = "step-no";
    number.textContent = String(index + 1);
    const copy = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = step.title || "Next";
    copy.appendChild(title);
    if (step.detail) {
      const detail = document.createElement("p");
      detail.textContent = step.detail;
      copy.appendChild(detail);
    }
    const actions = document.createElement("div");
    actions.className = "row";
    if (step.url) {
      const link = document.createElement("a");
      link.className = "btn";
      link.href = step.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open link";
      actions.appendChild(link);
    }
    if (step.mailto) {
      const mail = document.createElement("a");
      mail.className = "btn";
      mail.href = step.mailto;
      mail.textContent = "Send email";
      actions.appendChild(mail);
    }
    if (step.needs_letter && step.letter_action) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn primary";
      button.textContent = "Queue letter";
      button.addEventListener("click", () => queueGuideLetter(findingId, step.letter_action, button));
      actions.appendChild(button);
    }
    if (actions.childElementCount) copy.appendChild(actions);
    item.append(number, copy);
    list.appendChild(item);
  });
  body.appendChild(list);
}

function queueGuideLetter(findingId, action, button) {
  button.disabled = true;
  const body = new FormData();
  body.append("action", action);
  fetch("/findings/" + findingId + "/queue", { method: "POST", body })
    .then((response) => {
      if (!response.ok) throw new Error("queue");
      return response.json();
    })
    .then((data) => {
      const card = document.querySelector(".asset[data-finding='" + findingId + "']");
      if (card) {
        card.dataset.status = data.status || "confirmed";
        const pill = card.querySelector(".js-status");
        if (pill) {
          pill.className = "pill js-status status-" + card.dataset.status;
          pill.textContent = card.dataset.status;
        }
        paintActions(card, card.dataset.status);
      }
      showToast("Letter queued", "success");
      pollQueue();
    })
    .catch(() => {
      button.disabled = false;
      showToast("Could not queue that letter", "error");
    });
}

function bindGuides() {
  const dialog = document.getElementById("guide-dialog");
  if (!dialog) return;
  const title = document.getElementById("guide-title");
  const body = document.getElementById("guide-body");
  let currentId = "";

  function request(refresh) {
    body.replaceChildren();
    const note = document.createElement("p");
    note.textContent = "Looking up the current close path…";
    body.appendChild(note);
    document.getElementById("guide-refresh").disabled = true;
    const path = "/findings/" + currentId + "/guide";
    return fetch(path, { method: refresh ? "POST" : "GET" })
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then((result) => {
        document.getElementById("guide-refresh").disabled = false;
        if (!result.ok) {
          body.replaceChildren();
          const fail = document.createElement("p");
          fail.textContent = (result.data && result.data.detail) || "The close guide could not be prepared.";
          body.appendChild(fail);
          showToast(fail.textContent, "error");
          return;
        }
        paintGuide(result.data, currentId);
      })
      .catch(() => {
        document.getElementById("guide-refresh").disabled = false;
        body.replaceChildren();
        const fail = document.createElement("p");
        fail.textContent = "The close guide could not be prepared.";
        body.appendChild(fail);
        showToast(fail.textContent, "error");
      });
  }

  document.querySelectorAll("[data-guide]").forEach((button) => {
    button.addEventListener("click", () => {
      currentId = button.dataset.guide;
      const card = button.closest(".asset");
      const label = card ? card.querySelector("strong") : null;
      title.textContent = label ? label.textContent : "Close this asset";
      dialog.showModal();
      fetch("/findings/" + currentId + "/guide")
        .then((response) => response.json())
        .then((data) => {
          if (data.has_key && !data.guide) return request(true);
          paintGuide(data, currentId);
        })
        .catch(() => showToast("The close guide could not be prepared.", "error"));
    });
  });
  document.getElementById("guide-close").addEventListener("click", () => dialog.close());
  document.getElementById("guide-refresh").addEventListener("click", () => request(true));
}

readNotice();
bindTheme();
bindConfirm();
bindFindingActions();
bindAssetCards();
bindKickerBack();
bindSourceMessages();
function bindVaultLogin() {
  document.querySelectorAll("[data-vault-login]").forEach((button) => {
    button.addEventListener("click", () => {
      button.disabled = true;
      fetch("/findings/" + button.dataset.vaultLogin + "/vault-login", { method: "POST" })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then((result) => {
          button.disabled = false;
          if (!result.ok) {
            showToast((result.data && result.data.detail) || "Could not save that login", "error");
            return;
          }
          showToast(result.data.message || "Saved to the vault.", result.data.already ? "info" : "success");
        })
        .catch(() => {
          button.disabled = false;
          showToast("Could not save that login", "error");
        });
    });
  });
}

bindGuides();
bindVaultLogin();
function bindFileNames() {
  document.querySelectorAll("input[type='file']").forEach((input) => {
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      const label = input.closest("label");
      if (!label) return;
      let note = label.querySelector(".file-chosen");
      if (!note) {
        note = document.createElement("span");
        note.className = "pill file-chosen";
        label.insertBefore(note, input);
      }
      note.textContent = file ? "Selected: " + file.name : "";
    });
  });
}

function renderPdf() {
  const host = document.getElementById("pdf-pages");
  if (!host || !window.pdfjsLib || !host.dataset.src) return;
  host.replaceChildren();
  pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/pdf.worker.min.js";
  pdfjsLib.getDocument(host.dataset.src).promise.then(async (pdf) => {
    const cssWidth = Math.max(host.clientWidth || 720, 320);
    const pixelRatio = window.devicePixelRatio || 1;
    for (let number = 1; number <= pdf.numPages; number += 1) {
      const page = await pdf.getPage(number);
      const base = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: (cssWidth / base.width) * pixelRatio });
      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = cssWidth + "px";
      canvas.style.height = (viewport.height / pixelRatio) + "px";
      host.appendChild(canvas);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
    }
    if (new URLSearchParams(location.search).get("print") === "1") window.print();
  }).catch(() => showToast("Could not open that document", "error"));
}

function bindCredentials() {
  const dialog = document.getElementById("credential-dialog");
  const form = document.getElementById("credential-form");
  if (!dialog || !form) return;
  const kindSelect = document.getElementById("credential-kind");
  const showKind = () => {
    document.querySelectorAll(".credential-field").forEach((label) => {
      const on = label.dataset.kind === kindSelect.value;
      label.hidden = !on;
      label.querySelectorAll("input, textarea").forEach((input) => {
        input.disabled = !on;
      });
    });
  };
  kindSelect.addEventListener("change", showKind);
  showKind();
  document.getElementById("credential-close").addEventListener("click", () => dialog.close());
  document.getElementById("credential-add").addEventListener("click", () => {
    form.reset();
    document.getElementById("credential-id").value = "";
    document.getElementById("credential-title").textContent = "Add a secret";
    showKind();
    dialog.showModal();
  });
  document.querySelectorAll(".js-reveal").forEach((button) => {
    button.addEventListener("click", () => {
      const secret = button.parentElement.querySelector(".secret");
      const shown = secret.dataset.shown === "1";
      secret.textContent = shown ? "••••••••" : (secret.dataset.secret || "");
      secret.dataset.shown = shown ? "" : "1";
      button.setAttribute("aria-label", shown ? "Show secret" : "Hide secret");
    });
  });
  document.querySelectorAll(".js-copy").forEach((button) => {
    button.addEventListener("click", () => {
      const secret = button.parentElement.querySelector(".secret");
      const value = secret.dataset.secret || "";
      if (!value || !navigator.clipboard) {
        showToast("Nothing to copy", "alert");
        return;
      }
      navigator.clipboard.writeText(value).then(
        () => showToast("Copied", "success"),
        () => showToast("Could not copy", "error")
      );
    });
  });
  document.querySelectorAll(".js-edit").forEach((button) => {
    button.addEventListener("click", () => {
      let fields = {};
      try {
        fields = JSON.parse(button.getAttribute("data-fields") || "{}");
      } catch (error) {
        showToast("Could not open that entry", "error");
        return;
      }
      form.reset();
      document.getElementById("credential-id").value = button.dataset.id;
      kindSelect.value = button.dataset.kind;
      document.getElementById("credential-title").textContent = "Edit secret";
      showKind();
      Object.entries(fields).forEach(([name, value]) => {
        form.querySelectorAll("[name='" + name + "']").forEach((input) => {
          if (!input.disabled) input.value = value;
        });
      });
      dialog.showModal();
    });
  });
}

function bindReplyStatus() {
  const form = document.getElementById("reply-form");
  const select = document.getElementById("reply-status");
  const extra = document.getElementById("reply-extra");
  if (!form || !select || !extra) return;
  const toggle = () => {
    extra.hidden = select.value !== "received";
  };
  select.addEventListener("change", toggle);
  form.addEventListener("submit", (event) => {
    if (select.value !== "received") return;
    const note = (form.querySelector("[name='reply_note']").value || "").trim();
    const file = form.querySelector("[name='reply_file']").files;
    const hasFile = form.dataset.hasFile === "1" || (file && file.length);
    if (!note && !hasFile) {
      event.preventDefault();
      showToast("Add the response file or a note before marking it received.", "error");
    }
  });
}

function bindCaseViewer() {
  const host = document.getElementById("pdf-pages");
  if (!host) return;
  document.querySelectorAll("[data-view-src]").forEach((button) => {
    button.addEventListener("click", () => {
      const src = button.dataset.viewSrc || "";
      if (!src) return;
      host.dataset.src = src;
      host.classList.remove("case-empty");
      if (/\.(png|jpe?g)(\?|$)/i.test(src)) {
        host.replaceChildren();
        const image = document.createElement("img");
        image.src = src;
        image.alt = "Response";
        host.appendChild(image);
        return;
      }
      renderPdf();
    });
  });
}

function bindPitch() {
  const button = document.getElementById("pitch-fullscreen");
  const stage = document.getElementById("pitch-stage");
  const canvas = document.getElementById("pitch-canvas");
  const host = document.getElementById("pdf-pages");
  if (!button || !stage || !canvas || !host || !host.dataset.src || !window.pdfjsLib) return;
  let pdf = null;
  let pageNumber = 1;
  let renderTask = null;
  let renderToken = 0;
  const slideBox = new Map();
  pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/pdf.worker.min.js";
  const loading = pdfjsLib.getDocument(host.dataset.src).promise;

  async function slideFractions(page) {
    if (slideBox.has(page.pageNumber)) return slideBox.get(page.pageNumber);
    const probe = page.getViewport({ scale: 0.5, rotation: page.rotate || 0 });
    const sample = document.createElement("canvas");
    sample.width = Math.ceil(probe.width);
    sample.height = Math.ceil(probe.height);
    await page.render({ canvasContext: sample.getContext("2d", { willReadFrequently: true }), viewport: probe }).promise;
    const ctx = sample.getContext("2d", { willReadFrequently: true });
    const width = sample.width;
    const height = sample.height;
    const data = ctx.getImageData(0, 0, width, height).data;
    const bgAt = (x, y) => {
      const i = (y * width + x) * 4;
      return [data[i], data[i + 1], data[i + 2]];
    };
    const bg = bgAt(0, 0);
    const isMargin = (i) => Math.abs(data[i] - bg[0]) < 18 && Math.abs(data[i + 1] - bg[1]) < 18 && Math.abs(data[i + 2] - bg[2]) < 18;
    let minX = width;
    let minY = height;
    let maxX = 0;
    let maxY = 0;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const i = (y * width + x) * 4;
        if (isMargin(i)) continue;
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
    }
    let box = { sx: 0, sy: 0, sw: 1, sh: 1 };
    if (maxX > minX && maxY > minY) {
      let sx = minX / width;
      let sy = minY / height;
      let sw = (maxX - minX + 1) / width;
      let sh = (maxY - minY + 1) / height;
      const pixelAspect = (sw * width) / (sh * height);
      if (pixelAspect > 1.65 && pixelAspect < 1.9) {
        sh = (sw * width * 9) / (height * 16);
        sy = Math.max(0, Math.min(1 - sh, ((minY + maxY) / 2) / height - sh / 2));
      }
      if (sw < 0.98 || sh < 0.98) box = { sx, sy, sw, sh };
    }
    slideBox.set(page.pageNumber, box);
    return box;
  }

  function live() {
    return document.documentElement.classList.contains("pitch-live");
  }

  async function draw() {
    const token = ++renderToken;
    if (renderTask) {
      renderTask.cancel();
      renderTask = null;
    }
    if (!pdf) pdf = await loading;
    if (token !== renderToken) return;
    const page = await pdf.getPage(pageNumber);
    if (token !== renderToken) return;
    const box = await slideFractions(page);
    if (token !== renderToken) return;
    const rotation = page.rotate || 0;
    const base = page.getViewport({ scale: 1, rotation });
    const pixelRatio = window.devicePixelRatio || 1;
    const scale = Math.min(window.innerWidth / (base.width * box.sw), window.innerHeight / (base.height * box.sh)) * pixelRatio;
    const viewport = page.getViewport({ scale, rotation });
    const cropX = Math.ceil(viewport.width * box.sx);
    const cropY = Math.ceil(viewport.height * box.sy);
    const cropW = Math.floor(viewport.width * (box.sx + box.sw)) - cropX;
    const cropH = Math.floor(viewport.height * (box.sy + box.sh)) - cropY;
    const sheet = document.createElement("canvas");
    sheet.width = Math.ceil(viewport.width);
    sheet.height = Math.ceil(viewport.height);
    const task = page.render({ canvasContext: sheet.getContext("2d"), viewport });
    renderTask = task;
    try {
      await task.promise;
    } catch (error) {
      if (error && error.name === "RenderingCancelledException") return;
      showToast("Could not open that page", "error");
      return;
    }
    if (token !== renderToken) return;
    canvas.width = Math.max(1, Math.ceil(cropW));
    canvas.height = Math.max(1, Math.ceil(cropH));
    let cssW = cropW / pixelRatio;
    let cssH = cropH / pixelRatio;
    if (Math.abs(cssW - window.innerWidth) < 4) cssW = window.innerWidth;
    if (Math.abs(cssH - window.innerHeight) < 4) cssH = window.innerHeight;
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
    const inset = 2;
    canvas.getContext("2d").drawImage(
      sheet,
      cropX + inset,
      cropY + inset,
      Math.max(1, cropW - inset * 2),
      Math.max(1, cropH - inset * 2),
      0,
      0,
      canvas.width,
      canvas.height
    );
  }

  async function show(delta) {
    if (!pdf) pdf = await loading;
    const next = Math.min(pdf.numPages, Math.max(1, pageNumber + delta));
    if (delta !== 0 && next === pageNumber) return;
    pageNumber = next;
    await draw();
  }

  function closeStage() {
    document.documentElement.classList.remove("pitch-live");
    stage.hidden = true;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }

  button.addEventListener("click", async () => {
    stage.hidden = false;
    document.documentElement.classList.add("pitch-live");
    const root = document.documentElement;
    const request = root.requestFullscreen || root.webkitRequestFullscreen;
    if (request) {
      try {
        await request.call(root);
      } catch (error) {
        /* The page still covers the screen when the browser blocks fullscreen. */
      }
    }
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await show(0);
  });
  stage.addEventListener("click", (event) => {
    if (!live()) return;
    const mid = stage.getBoundingClientRect().left + stage.clientWidth / 2;
    show(event.clientX < mid ? -1 : 1);
  });
  document.addEventListener("fullscreenchange", () => {
    if (!live()) return;
    if (!document.fullscreenElement && !document.webkitFullscreenElement) closeStage();
  });
  window.addEventListener("resize", () => {
    if (live()) draw();
  });
  document.addEventListener("keydown", (event) => {
    if (!live()) return;
    if (event.key === "ArrowRight" || event.key === "PageDown" || event.key === " ") {
      event.preventDefault();
      show(1);
    } else if (event.key === "ArrowLeft" || event.key === "PageUp") {
      event.preventDefault();
      show(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      pageNumber = 1;
      draw();
    } else if (event.key === "End" && pdf) {
      event.preventDefault();
      pageNumber = pdf.numPages;
      draw();
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeStage();
    }
  });
}

bindPitch();
bindCaseViewer();
bindReplyStatus();
bindCredentials();
bindStepDialog();
bindFileNames();
pollQueue();
renderPdf();

const params = new URLSearchParams(location.search);
if (params.get("run")) pollRun(params.get("run"));
const active = document.querySelector(".runs [data-status='running'], .runs [data-status='queued']");
if (active && !params.get("run")) pollRun(active.dataset.run);
