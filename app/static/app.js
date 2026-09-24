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
  if (status !== "confirmed") {
    const button = iconButton("Confirm", "confirm");
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
  const label = document.createElement("label");
  label.className = "step-choice";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.name = "action";
  box.value = value;
  const text = document.createElement("span");
  text.textContent = value;
  label.append(box, text);
  return label;
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
  paintStepHistory([]);
  dialog.showModal();
  loadStepHistory(card.dataset.finding);
}

function paintStepHistory(jobs) {
  const list = document.getElementById("step-history");
  if (!list) return;
  list.replaceChildren();
  jobs.forEach((job) => {
    const item = document.createElement("li");
    const action = document.createElement("span");
    action.textContent = job.action;
    const pill = document.createElement("span");
    pill.className = "pill status-" + job.status;
    pill.textContent = job.status;
    item.append(action, pill);
    if (job.ready) {
      const link = document.createElement("a");
      link.href = "/queue/" + job.id + "/packet";
      link.textContent = "Download";
      item.appendChild(link);
    }
    list.appendChild(item);
  });
}

function loadStepHistory(findingId) {
  fetch("/queue.json")
    .then((response) => response.json())
    .then((data) => {
      const jobs = (data.jobs || []).filter((job) => String(job.finding_id) === String(findingId));
      paintStepHistory(jobs);
    })
    .catch(() => {});
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
          card.dataset.status = "confirmed";
          const pill = card.querySelector(".js-status");
          if (pill) {
            pill.className = "pill js-status status-confirmed";
            pill.textContent = "confirmed";
          }
          paintActions(card, "confirmed");
          document.getElementById("step-title").textContent = "Add a step";
          if (data.counts) {
            setCount("candidate", data.counts.candidate);
            setCount("confirmed", data.counts.confirmed);
            setCount("dismissed", data.counts.dismissed);
            setCount("active", data.counts.active);
            setCount("all", data.counts.all);
          }
        }
        document.querySelectorAll("#step-options input").forEach((box) => {
          box.checked = false;
        });
        document.getElementById("step-custom").replaceChildren();
        customStepRow();
        loadStepHistory(dialog.dataset.finding);
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
        setCount("candidate", data.counts.candidate);
        setCount("confirmed", data.counts.confirmed);
        setCount("dismissed", data.counts.dismissed);
        setCount("active", data.counts.active);
        setCount("all", data.counts.all);
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
      openStepDialog(card);
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
bindSourceMessages();
bindGuides();
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
  if (!host || !window.pdfjsLib) return;
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
