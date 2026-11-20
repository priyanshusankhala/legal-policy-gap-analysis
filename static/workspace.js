"use strict";

const byId = (id) => document.getElementById(id);

let dutyRequest = 0;
let documentRequest = 0;

function node(tag, text = "", className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = className;
  return element;
}

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  const data = await response.json();

  if (!response.ok) {
    const message = typeof data.detail === "string"
      ? data.detail
      : `Request failed: ${response.status}`;
    throw new Error(message);
  }

  return data;
}

function statusBadge(state) {
  const styles = {
    met: ["MET", "bg-emerald-500/20 text-emerald-300"],
    open: ["OPEN — CONFIRMED GAP", "bg-rose-500/20 text-rose-300"],
    evidence_missing: [
      "EVIDENCE MISSING",
      "bg-amber-500/20 text-amber-300",
    ],
  };

  const [label, color] = styles[state] || [
    "UNKNOWN STATE",
    "bg-slate-700 text-white",
  ];

  return node(
    "span",
    label,
    `inline-block px-3 py-1 rounded text-xs font-bold ${color}`,
  );
}

function clearEvaluation(message) {
  byId("duty-title").textContent = message;
  byId("statutory-ref").textContent = "";
  byId("duty-reason").textContent = "";
  byId("state-badge-container").replaceChildren();
  byId("components-container").replaceChildren();
  byId("exclusion-container").replaceChildren();
  byId("followup-card").replaceChildren();
  byId("followup-card").classList.add("hidden");
}

async function loadDuties() {
  try {
    const duties = await getJson("/api/duties");
    const list = byId("duty-list");
    list.replaceChildren();

    for (const duty of duties) {
      const button = node(
        "button",
        "",
        "w-full text-left p-4 rounded-lg border border-slate-600 "
          + "bg-slate-700/40 hover:bg-slate-700",
      );

      button.type = "button";
      button.dataset.dutyId = duty.id;
      button.append(
        node("div", duty.id, "font-mono text-blue-400 mb-2"),
        node("div", duty.title, "text-sm mb-2"),
        statusBadge(duty.state),
      );

      button.addEventListener("click", () => selectDuty(duty.id));
      list.append(button);
    }

    if (duties.length) {
      await selectDuty(duties[0].id);
    } else {
      clearEvaluation("No duty results available.");
    }
  } catch (error) {
    clearEvaluation(`Could not load duties: ${error.message}`);
  }
}

async function selectDuty(dutyId) {
  const requestId = ++dutyRequest;

  document.querySelectorAll("[data-duty-id]").forEach((button) => {
    const selected = button.dataset.dutyId === dutyId;
    button.setAttribute("aria-pressed", String(selected));
    button.classList.toggle("ring-2", selected);
    button.classList.toggle("ring-blue-500", selected);
  });

  clearEvaluation(`Loading ${dutyId}…`);

  try {
    const data = await getJson(
      `/api/evaluate/${encodeURIComponent(dutyId)}`,
    );

    if (requestId !== dutyRequest) return;

    if (data.duty_id !== dutyId) {
      throw new Error("Server returned a different duty.");
    }

    renderEvaluation(data);
  } catch (error) {
    if (requestId === dutyRequest) {
      clearEvaluation(`Could not load ${dutyId}: ${error.message}`);
    }
  }
}

function renderCitation(citation) {
  const button = node(
    "button",
    "",
    "block w-full text-left mt-3 p-3 rounded bg-slate-950 "
      + "border border-slate-700 hover:border-blue-400",
  );

  button.type = "button";
  button.append(
    node(
      "div",
      `Open source: ${citation.source_id}`,
      "text-xs text-blue-400 font-semibold",
    ),
    node(
      "div",
      citation.location,
      "text-xs text-slate-400 mt-1",
    ),
    node(
      "div",
      `Version: ${citation.version || "unspecified"} · `
        + `Date: ${citation.date || "unspecified"} · `
        + `Status: ${citation.status || "unspecified"}`,
      "text-xs text-slate-400 mt-1",
    ),
    node(
      "pre",
      citation.exact_passage,
      "text-xs text-amber-200 whitespace-pre-wrap break-words mt-2",
    ),
    node(
      "p",
      citation.demonstrates,
      "text-xs text-slate-300 mt-2",
    ),
  );

  button.addEventListener("click", () => {
    openDocument(citation.file_path, citation.exact_passage);
  });

  return button;
}

function renderEvaluation(data) {
  byId("duty-title").textContent =
    `${data.duty_id} · ${data.duty_title}`;
  byId("statutory-ref").textContent = data.statutory_ref;
  byId("duty-reason").textContent = data.reason;
  byId("state-badge-container").replaceChildren(
    statusBadge(data.state),
  );

  const components = byId("components-container");
  components.replaceChildren();

  for (const component of data.components) {
    const card = node(
      "article",
      "",
      "p-4 rounded-lg bg-slate-900 border border-slate-700",
    );

    card.append(
      node("h4", component.name, "font-bold text-sm"),
      node(
        "p",
        component.status.replaceAll("_", " ").toUpperCase(),
        "text-xs text-blue-300 mt-2",
      ),
      node("p", component.rationale, "text-sm mt-2"),
    );

    for (const citation of component.citations || []) {
      card.append(renderCitation(citation));
    }

    for (const limitation of component.limitations || []) {
      card.append(
        node(
          "p",
          `Limitation: ${limitation}`,
          "text-xs text-slate-400 italic mt-2",
        ),
      );
    }

    components.append(card);
  }

  const followup = byId("followup-card");
  followup.replaceChildren();
  followup.classList.toggle("hidden", !data.actionable_request);

  if (data.actionable_request) {
    followup.append(
      node("h3", "Evidence request", "font-bold text-amber-300"),
      node(
        "p",
        data.actionable_request.missing_fact,
        "text-sm mt-2",
      ),
      node(
        "p",
        data.actionable_request.focused_question,
        "text-sm italic mt-3",
      ),
    );
  }

  const exclusions = byId("exclusion-container");
  exclusions.replaceChildren();

  for (const item of data.exclusion_log || []) {
    const card = node(
      "div",
      "",
      "p-3 rounded bg-slate-900 border border-slate-700",
    );
    const button = node(
      "button",
      `Open source: ${item.source_id}`,
      "text-blue-400 underline text-left",
    );

    button.type = "button";
    button.addEventListener("click", () => openDocument(item.file_path));

    card.append(
      button,
      node("p", `${item.disposition}: ${item.reason}`, "mt-2"),
    );
    exclusions.append(card);
  }

  if (!exclusions.childElementCount) {
    exclusions.append(
      node("p", "No exclusions recorded for this duty."),
    );
  }
}

async function openDocument(filePath, quote = "") {
  const requestId = ++documentRequest;
  const content = byId("modal-doc-content");

  byId("modal-doc-title").textContent = filePath.split("/").pop();
  byId("modal-doc-path").textContent = filePath;
  byId("doc-modal").classList.remove("hidden");
  content.textContent = "Loading document…";

  try {
    const data = await getJson(
      `/api/document?file_path=${encodeURIComponent(filePath)}`,
    );

    if (requestId !== documentRequest) return;

    const text = data.content;
    const passage = quote.trim();
    const position = passage ? text.indexOf(passage) : -1;

    content.replaceChildren();
    content.scrollTop = 0;

    if (position < 0) {
      if (passage) {
        content.append(
          node(
            "p",
            "Warning: exact quotation was not found. "
              + "Verify this citation against the source.",
            "text-amber-300 mb-4",
          ),
        );
      }

      content.append(document.createTextNode(text));
      return;
    }

    const mark = node(
      "mark",
      passage,
      "bg-amber-300 text-slate-950",
    );

    content.append(
      document.createTextNode(text.slice(0, position)),
      mark,
      document.createTextNode(text.slice(position + passage.length)),
    );

    requestAnimationFrame(() => {
      mark.scrollIntoView({ block: "center" });
    });
  } catch (error) {
    if (requestId === documentRequest) {
      content.textContent = `Could not open document: ${error.message}`;
    }
  }
}

function closeModal() {
  documentRequest += 1;
  byId("doc-modal").classList.add("hidden");
}

// Existing HTML close buttons call this function.
window.closeModal = closeModal;

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeModal();
});

loadDuties();
