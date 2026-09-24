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

function paintActions(card, status) {
  const row = card.querySelector("[data-actions]");
  const id = card.dataset.finding;
  const back = currentView();
  row.replaceChildren();
  if (status !== "confirmed") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn primary";
    button.textContent = "Confirm";
    button.addEventListener("click", () => openStepDialog(card));
    row.appendChild(button);
  }
  const form = document.createElement("form");
  form.method = "post";
  form.action = "/findings/" + id + "/status";
  const value = status === "dismissed" ? "candidate" : "dismissed";
  const label = status === "dismissed" ? "Restore" : "Dismiss";
  form.innerHTML = '<input type="hidden" name="status" value="' + value + '"><input type="hidden" name="back" value="' + back + '">';
  const button = document.createElement("button");
  button.className = "btn";
  button.type = "submit";
  button.textContent = label;
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

function openStepDialog(card) {
  const dialog = document.getElementById("step-dialog");
  const select = document.getElementById("step-action");
  const options = estateActions()[card.dataset.category] || estateActions().other || [];
  document.getElementById("step-title").textContent = card.dataset.status === "confirmed" ? "Add a step" : "Next step";
  document.getElementById("step-asset").textContent = card.querySelector("strong").textContent;
  document.getElementById("step-note").value = "";
  select.replaceChildren();
  options.forEach((action) => {
    const option = document.createElement("option");
    option.value = action;
    option.textContent = action;
    select.appendChild(option);
  });
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
    pill.className = "pill status-" + job.status;
    pill.textContent = job.status;
    item.append(text, pill);
    if (job.ready) {
      const link = document.createElement("a");
      link.className = "btn";
      link.href = "/queue/" + job.id + "/packet";
      link.textContent = "Download";
      item.appendChild(link);
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
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const card = document.querySelector('.asset[data-finding="' + dialog.dataset.finding + '"]');
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
        document.getElementById("step-note").value = "";
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

readNotice();
bindTheme();
bindConfirm();
bindFindingActions();
bindAssetCards();
bindSourceMessages();
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

bindStepDialog();
bindFileNames();
pollQueue();

const params = new URLSearchParams(location.search);
if (params.get("run")) pollRun(params.get("run"));
const active = document.querySelector(".runs [data-status='running'], .runs [data-status='queued']");
if (active && !params.get("run")) pollRun(active.dataset.run);
