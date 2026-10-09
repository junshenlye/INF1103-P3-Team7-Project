// Tab navigation, the grouped "needs your attention" dropdown, and the live
// timer on the build button. Purely presentational — app.js (form handling,
// AJAX submit) is untouched.
(function () {
  /* ---------- Tabs ---------- */
  const tabButtons = Array.from(document.querySelectorAll(".tab"));
  const tabPanels = Array.from(document.querySelectorAll(".tab-panel"));

  function activate(targetId) {
    tabButtons.forEach((button) => {
      const isTarget = button.dataset.tabTarget === targetId;
      button.classList.toggle("is-active", isTarget);
      button.setAttribute("aria-selected", isTarget ? "true" : "false");
    });
    tabPanels.forEach((panel) => {
      const isTarget = panel.id === targetId;
      panel.classList.toggle("is-active", isTarget);
      panel.hidden = !isTarget;
    });
  }

  tabButtons.forEach((button) => {
    button.addEventListener("click", () => activate(button.dataset.tabTarget));
  });

  document.querySelector(".tab-bar")?.addEventListener("keydown", (event) => {
    if (!["ArrowRight", "ArrowLeft"].includes(event.key)) return;
    const i = tabButtons.findIndex((b) => b.classList.contains("is-active"));
    const n = event.key === "ArrowRight" ? (i + 1) % tabButtons.length : (i - 1 + tabButtons.length) % tabButtons.length;
    tabButtons[n].focus();
    activate(tabButtons[n].dataset.tabTarget);
  });

  document.querySelector("#back-to-add")?.addEventListener("click", () => activate("tab-add"));
  if (document.body.dataset.hasSchedule === "true") activate("tab-schedule");

  /* ---------- Attention dropdown (grouped by module, plain language) ---------- */
  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function escapeRegex(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  function tidyName(text) {
    return text.replace(/\([^)]*\)/g, "").replace(/\s+/g, " ").replace(/^[\s:–-]+|[\s:–-]+$/g, "").trim();
  }
  function sentence(text) {
    const t = text.trim().replace(/\s+/g, " ");
    return (t.charAt(0).toUpperCase() + t.slice(1)).replace(/[.\s]*$/, ".");
  }
  function joinNames(names) {
    const list = Array.from(names);
    if (list.length <= 1) return list.join("");
    return list.slice(0, -1).join(", ") + " and " + list[list.length - 1];
  }

  function buildAttention() {
    const root = document.getElementById("attention-root");
    const dataEl = document.getElementById("attention-data");
    if (!root || !dataEl) return;
    let data;
    try { data = JSON.parse(dataEl.textContent); } catch (_e) { return; }

    const modules = new Set();
    const assessments = [];
    (data.coverage || []).forEach((m) => m.module_name && modules.add(m.module_name));
    (data.ranking || []).forEach((r) => {
      if (r.module_name) modules.add(r.module_name);
      if (r.module_name && r.assessment_name) assessments.push({ module: r.module_name, name: r.assessment_name });
    });
    assessments.sort((a, b) => b.name.length - a.name.length);

    const groups = new Map();
    function group(name) {
      if (!groups.has(name)) groups.set(name, { noTiming: new Set(), noDetails: new Set(), notes: new Set() });
      return groups.get(name);
    }
    function findModule(text) {
      for (const m of modules) if (new RegExp("\\b" + escapeRegex(m) + "\\b", "i").test(text)) return m;
      const lower = text.toLowerCase();
      for (const a of assessments) if (lower.includes(a.name.toLowerCase().replace(/s$/, ""))) return a.module;
      return null;
    }

    const items = [].concat(data.comments || [], data.checklist || []).map(String);
    items.forEach((raw) => {
      const text = raw.trim();
      if (!text) return;
      const mod = findModule(text);

      let m = text.match(/^(.*?):\s*assessment timing is missing/i);
      if (m) {
        const name = tidyName(mod ? m[1].replace(new RegExp(escapeRegex(mod), "i"), "") : m[1]);
        if (name) group(mod || "General").noTiming.add(name);
        return;
      }
      m = text.match(/^(.*?):\s*assessment details are incomplete/i);
      if (m) {
        const name = tidyName(mod ? m[1].replace(new RegExp(escapeRegex(mod), "i"), "") : m[1]);
        if (name) group(mod || "General").noDetails.add(name);
        return;
      }
      // Skip vague / duplicate lines already covered by the per-module notes above.
      if (/obtain specific scheduling|additional assessment detail/i.test(text)) return;
      // Keep only things the student can act on; drop purely informational AI notes.
      if (/^(confirm|verify|check|clarify|ask|make sure)\b/i.test(text)) {
        group(mod || "General").notes.add(sentence(text));
      }
    });

    (data.coverage || []).forEach((c) => {
      if (c.complete === false && c.module_name) {
        const known = Math.round((Number(c.known_weightage_percent) || 0) * 10) / 10;
        group(c.module_name).notes.add(`Only ${known}% of the grade is filled in so far. Add the remaining weightage.`);
      }
    });

    const entries = [];
    groups.forEach((g, name) => {
      const lines = [];
      if (g.noTiming.size) lines.push(`No week or date set yet for ${joinNames(g.noTiming)}.`);
      if (g.noDetails.size) lines.push(`Missing some details (like weightage) for ${joinNames(g.noDetails)}.`);
      g.notes.forEach((n) => lines.push(n));
      if (lines.length) entries.push({ name, lines });
    });
    entries.sort((a, b) => (a.name === "General") - (b.name === "General") || a.name.localeCompare(b.name));
    if (!entries.length) return;

    const total = entries.reduce((n, e) => n + e.lines.length, 0);
    root.innerHTML =
      `<summary><span class="attention-icon" aria-hidden="true">!</span>` +
      `<span class="attention-title"><strong>A few things need your attention</strong>` +
      `<span>${total} thing${total === 1 ? "" : "s"} across ${entries.length} module${entries.length === 1 ? "" : "s"}. Tap to see what to fix.</span></span>` +
      `<span class="chevron" aria-hidden="true"></span></summary>` +
      `<div class="attention-body">` +
      entries.map((e) =>
        `<details class="mod-group"><summary><span>${escapeHtml(e.name)}</span>` +
        `<span class="mod-count">${e.lines.length}</span><span class="chevron" aria-hidden="true"></span></summary>` +
        `<ul>${e.lines.map((l) => `<li>${escapeHtml(l)}</li>`).join("")}</ul></details>`).join("") +
      `</div>`;
    root.hidden = false;
  }
  buildAttention();

  /* ---------- Priority grid: modules (rows) x weeks (columns), dot colour = priority ---------- */
  function buildPriorityGrid() {
    const table = document.getElementById("priority-grid");
    const dataEl = document.getElementById("schedule-data");
    const filterBar = document.getElementById("grid-filters");
    const tip = document.getElementById("dot-tip");
    if (!table || !dataEl) return;
    let data;
    try { data = JSON.parse(dataEl.textContent); } catch (_e) { return; }

    const weeks = (data.timeline || []).map((w) => ({ number: w.week, label: w.label || `Week ${w.week}`, items: w.assessments || [] }));
    if (!weeks.length) return;

    // Priority comes from the backend's relative ranking (importance x proximity):
    // top third = high, middle third = medium, bottom third = low. Anything the
    // backend could not score falls back to weightage, or "unknown".
    const key = (m, a) => `${m}||${a}`;
    const ranked = (data.ranking || [])
      .filter((r) => r.relative_score !== null && r.relative_score !== undefined && !isNaN(Number(r.relative_score)))
      .sort((a, b) => Number(b.relative_score) - Number(a.relative_score));
    const level = new Map();
    ranked.forEach((r, i) => {
      const share = (i + 1) / ranked.length;
      level.set(key(r.module_name, r.assessment_name), share <= 1 / 3 ? "high" : share <= 2 / 3 ? "medium" : "low");
    });
    function priorityOf(item) {
      const known = level.get(key(item.module_name, item.assessment_name));
      if (known) return known;
      const w = item.weightage_percent;
      if (w === null || w === undefined || isNaN(Number(w))) return "unknown";
      return Number(w) >= 30 ? "high" : Number(w) >= 15 ? "medium" : "low";
    }
    const order = { unknown: 0, low: 1, medium: 2, high: 3 };
    const names = { high: "High priority", medium: "Medium priority", low: "Low priority", unknown: "Not enough info to rank" };
    const chipNames = { high: "High", medium: "Medium", low: "Low", unknown: "Not enough info" };

    // One row per module the student entered, in the order they were entered.
    const moduleOrder = [];
    const addModule = (n) => { if (n && !moduleOrder.includes(n)) moduleOrder.push(n); };
    (data.coverage || []).forEach((c) => addModule(c.module_name));
    (data.ranking || []).forEach((r) => addModule(r.module_name));
    weeks.forEach((w) => w.items.forEach((i) => addModule(i.module_name)));

    const cells = new Map(); // module -> weekNumber -> [{item, p}]
    const best = new Map();  // module -> strongest priority
    const present = new Set(); // priorities that actually occur
    moduleOrder.forEach((m) => { cells.set(m, new Map()); best.set(m, -1); });
    weeks.forEach((w) => w.items.forEach((item) => {
      const row = cells.get(item.module_name);
      if (!row) return;
      const p = priorityOf(item);
      present.add(p);
      if (!row.has(w.number)) row.set(w.number, []);
      row.get(w.number).push({ item, p });
      best.set(item.module_name, Math.max(best.get(item.module_name), order[p]));
    }));

    let sortMode = 0; // 0 = as entered, 1 = high first, 2 = low first
    const pickedPriorities = new Set(); // empty = show all
    const pickedModules = new Set();    // empty = show all

    /* ----- filter chips ----- */
    function buildFilters() {
      if (!filterBar) return;
      const prioChips = ["high", "medium", "low", "unknown"].filter((p) => present.has(p)).map((p) =>
        `<button type="button" class="chip" data-prio="${p}" aria-pressed="false"><i class="dot p-${p}"></i>${chipNames[p]}</button>`).join("");
      const modChips = moduleOrder.map((m) =>
        `<button type="button" class="chip" data-mod="${escapeHtml(m)}" aria-pressed="false">${escapeHtml(m)}</button>`).join("");
      filterBar.innerHTML =
        `<div class="filter-group"><span class="filter-label">Priority</span>${prioChips}</div>` +
        (moduleOrder.length > 1 ? `<div class="filter-group"><span class="filter-label">Module</span>${modChips}</div>` : "") +
        `<button type="button" class="chip clear-chip" id="clear-filters" hidden>Clear filters</button>`;
    }
    function syncFilters() {
      if (!filterBar) return;
      filterBar.querySelectorAll("[data-prio]").forEach((c) => c.setAttribute("aria-pressed", pickedPriorities.has(c.dataset.prio)));
      filterBar.querySelectorAll("[data-mod]").forEach((c) => c.setAttribute("aria-pressed", pickedModules.has(c.dataset.mod)));
      const clear = filterBar.querySelector("#clear-filters");
      if (clear) clear.hidden = !(pickedPriorities.size || pickedModules.size);
    }

    /* ----- table ----- */
    function render() {
      hideTip();
      const showDot = (e) => !pickedPriorities.size || pickedPriorities.has(e.p);
      let rows = moduleOrder.filter((m) => !pickedModules.size || pickedModules.has(m));
      if (pickedPriorities.size) {
        rows = rows.filter((m) => [...cells.get(m).values()].some((list) => list.some(showDot)));
      }
      if (sortMode === 1) rows.sort((a, b) => best.get(b) - best.get(a));
      if (sortMode === 2) rows.sort((a, b) => best.get(a) - best.get(b));

      const sortHint = ["Sort by priority", "Showing high priority first", "Showing low priority first"][sortMode];
      const head1 =
        `<tr><th class="mod-col" rowspan="2"><button type="button" class="sort-btn" id="sort-modules" title="${sortHint}" aria-label="${sortHint}">` +
        `<span>Module</span><span class="sort-arrows" aria-hidden="true">↑↓</span></button></th>` +
        `<th class="wks-label" colspan="${weeks.length}">WKS</th></tr>`;
      const head2 = `<tr>${weeks.map((w) =>
        `<th title="${escapeHtml(w.label)}" class="${w.number === data.current_week ? "is-current-week" : ""}">${escapeHtml(w.number)}</th>`).join("")}</tr>`;
      const body = rows.length ? rows.map((m) =>
        `<tr><th scope="row" class="mod-col">${escapeHtml(m)}</th>` +
        weeks.map((w) => {
          const entries = (cells.get(m).get(w.number) || []).filter(showDot).sort((a, b) => order[b.p] - order[a.p]);
          const dots = entries.map((e) => {
            const weight = e.item.weightage_percent;
            const label = `${e.item.assessment_name}, ${m}, ${w.label}${weight !== null && weight !== undefined ? `, ${weight}%` : ""}, ${names[e.p]}`;
            return `<button type="button" class="pdot ${e.p}" aria-label="${escapeHtml(label)}"` +
              ` data-name="${escapeHtml(e.item.assessment_name)}" data-module="${escapeHtml(m)}" data-week="${escapeHtml(w.label)}"` +
              ` data-weight="${weight === null || weight === undefined ? "" : escapeHtml(weight)}" data-prio="${e.p}"></button>`;
          }).join("");
          return `<td class="${w.number === data.current_week ? "is-current-week" : ""}"><div class="cell-dots">${dots}</div></td>`;
        }).join("") + `</tr>`).join("")
        : `<tr><td class="no-match" colspan="${weeks.length + 1}">Nothing matches these filters.</td></tr>`;
      table.innerHTML = `<thead>${head1}${head2}</thead><tbody>${body}</tbody>`;
    }

    /* ----- hover / tap popover ----- */
    let pinned = null;
    function showTip(dot) {
      if (!tip) return;
      const weight = dot.dataset.weight;
      tip.innerHTML =
        `<strong>${escapeHtml(dot.dataset.name)}</strong>` +
        `<span class="tip-weight">${weight !== "" ? `${escapeHtml(weight)}% of the grade` : "Weightage not set"}</span>` +
        `<span class="tip-meta">${escapeHtml(dot.dataset.module)} · ${escapeHtml(dot.dataset.week)}</span>` +
        `<span class="tip-prio"><i class="dot p-${dot.dataset.prio}"></i>${names[dot.dataset.prio]}</span>`;
      tip.hidden = false;
      const host = tip.parentElement.getBoundingClientRect();
      const r = dot.getBoundingClientRect();
      const width = tip.offsetWidth;
      let left = r.left - host.left + r.width / 2 - width / 2;
      left = Math.max(8, Math.min(left, host.width - width - 8));
      tip.style.left = `${left}px`;
      tip.style.top = `${r.top - host.top - tip.offsetHeight - 10}px`;
      if (r.top - host.top - tip.offsetHeight - 10 < 0) tip.style.top = `${r.bottom - host.top + 10}px`;
    }
    function hideTip() {
      if (tip) tip.hidden = true;
      pinned = null;
    }

    table.addEventListener("pointerover", (e) => {
      const dot = e.target.closest(".pdot");
      if (dot && e.pointerType === "mouse" && !pinned) showTip(dot);
    });
    table.addEventListener("pointerout", (e) => {
      if (e.target.closest(".pdot") && e.pointerType === "mouse" && !pinned) tip.hidden = true;
    });
    table.addEventListener("focusin", (e) => { const dot = e.target.closest(".pdot"); if (dot) showTip(dot); });
    table.addEventListener("focusout", (e) => { if (e.target.closest(".pdot") && !pinned) tip.hidden = true; });
    table.addEventListener("click", (e) => {
      if (e.target.closest("#sort-modules")) {
        sortMode = (sortMode + 1) % 3;
        render();
        return;
      }
      const dot = e.target.closest(".pdot");
      if (!dot) return;
      if (pinned === dot) { hideTip(); return; }
      showTip(dot);
      pinned = dot; // a tap/click keeps it open until you tap elsewhere
    });
    document.addEventListener("click", (e) => { if (!e.target.closest(".pdot") && !e.target.closest("#dot-tip")) hideTip(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
    document.querySelector(".priority-scroll")?.addEventListener("scroll", hideTip);

    filterBar?.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      if (chip.id === "clear-filters") { pickedPriorities.clear(); pickedModules.clear(); }
      else if (chip.dataset.prio) {
        pickedPriorities.has(chip.dataset.prio) ? pickedPriorities.delete(chip.dataset.prio) : pickedPriorities.add(chip.dataset.prio);
      } else if (chip.dataset.mod) {
        pickedModules.has(chip.dataset.mod) ? pickedModules.delete(chip.dataset.mod) : pickedModules.add(chip.dataset.mod);
      }
      syncFilters();
      render();
    });

    buildFilters();
    syncFilters();
    render();
  }
  buildPriorityGrid();

  /* ---------- Live timer on the build button ---------- */
  const elapsed = document.getElementById("progress-elapsed");
  const timer = document.querySelector(".build-timer");
  const button = document.querySelector("#assessment-form button[type='submit']");
  if (elapsed && timer && button) {
    const sync = () => {
      timer.textContent = elapsed.textContent;
      timer.hidden = !button.disabled;
    };
    new MutationObserver(sync).observe(elapsed, { childList: true, characterData: true, subtree: true });
    new MutationObserver(sync).observe(button, { attributes: true, attributeFilter: ["disabled"] });
  }
})();