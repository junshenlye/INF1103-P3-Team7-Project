// tabs.js = tabs + "needs attention" list + priority grid + button timer
// (app.js handles the form, this file does not touch it)
(function () {
  // ================= TABS =================
  const tabButtons = Array.from(document.querySelectorAll(".tab"));        // the 2 tab buttons
  const tabPanels = Array.from(document.querySelectorAll(".tab-panel"));   // the 2 pages

  // show one panel (by id) and hide the other
  function activate(targetId) {
    tabButtons.forEach((button) => {
      const isTarget = button.dataset.tabTarget === targetId;
      button.classList.toggle("is-active", isTarget);                       // highlight the button
      button.setAttribute("aria-selected", isTarget ? "true" : "false");   // for screen readers
    });
    tabPanels.forEach((panel) => {
      const isTarget = panel.id === targetId;
      panel.classList.toggle("is-active", isTarget);
      panel.hidden = !isTarget;                                             // hide the other page
    });
  }

  // click a tab -> switch page
  tabButtons.forEach((button) => {
    button.addEventListener("click", () => activate(button.dataset.tabTarget));
  });

  // left/right arrow keys move between tabs
  document.querySelector(".tab-bar")?.addEventListener("keydown", (event) => {
    if (!["ArrowRight", "ArrowLeft"].includes(event.key)) return;
    const i = tabButtons.findIndex((b) => b.classList.contains("is-active"));   // current tab
    const n = event.key === "ArrowRight" ? (i + 1) % tabButtons.length : (i - 1 + tabButtons.length) % tabButtons.length;  // next (wraps around)
    tabButtons[n].focus();
    activate(tabButtons[n].dataset.tabTarget);
  });

  // "Add more info" button -> back to tab 1
  document.querySelector("#back-to-add")?.addEventListener("click", () => activate("tab-add"));
  // if a schedule already exists, open My Schedule first
  if (document.body.dataset.hasSchedule === "true") activate("tab-schedule");

  // ================= HELPER FUNCTIONS =================
  // make text safe to put inside HTML (stops < > & " ' breaking the page)
  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  // make text safe to use inside a regular expression
  function escapeRegex(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  // clean a name: remove (brackets), extra spaces, and leading/trailing : - symbols
  function tidyName(text) {
    return text.replace(/\([^)]*\)/g, "").replace(/\s+/g, " ").replace(/^[\s:–-]+|[\s:–-]+$/g, "").trim();
  }
  // turn text into a sentence: capital first letter + one full stop at the end
  function sentence(text) {
    const t = text.trim().replace(/\s+/g, " ");
    return (t.charAt(0).toUpperCase() + t.slice(1)).replace(/[.\s]*$/, ".");
  }
  // ["a","b","c"] -> "a, b and c"
  function joinNames(names) {
    const list = Array.from(names);
    if (list.length <= 1) return list.join("");
    return list.slice(0, -1).join(", ") + " and " + list[list.length - 1];
  }

  // ================= "A FEW THINGS NEED YOUR ATTENTION" DROPDOWN =================
  function buildAttention() {
    const root = document.getElementById("attention-root");       // the empty <details>
    const dataEl = document.getElementById("attention-data");     // JSON from the backend
    if (!root || !dataEl) return;
    let data;
    try { data = JSON.parse(dataEl.textContent); } catch (_e) { return; }   // read JSON, stop if broken

    // 1) collect all module names, and all assessments (used to guess which module a comment is about)
    const modules = new Set();
    const assessments = [];
    (data.coverage || []).forEach((m) => m.module_name && modules.add(m.module_name));
    (data.ranking || []).forEach((r) => {
      if (r.module_name) modules.add(r.module_name);
      if (r.module_name && r.assessment_name) assessments.push({ module: r.module_name, name: r.assessment_name });
    });
    assessments.sort((a, b) => b.name.length - a.name.length);    // longest names first so they match first

    // 2) groups = one bucket per module, each holds 3 lists of problems
    const groups = new Map();
    function group(name) {
      if (!groups.has(name)) groups.set(name, { noTiming: new Set(), noDetails: new Set(), notes: new Set() });
      return groups.get(name);
    }
    // find which module a comment is about (by module name first, then by assessment name)
    function findModule(text) {
      for (const m of modules) if (new RegExp("\\b" + escapeRegex(m) + "\\b", "i").test(text)) return m;
      const lower = text.toLowerCase();
      for (const a of assessments) if (lower.includes(a.name.toLowerCase().replace(/s$/, ""))) return a.module;
      return null;
    }

    // 3) go through every comment and put it in the right module's bucket
    const items = [].concat(data.comments || [], data.checklist || []).map(String);
    items.forEach((raw) => {
      const text = raw.trim();
      if (!text) return;
      const mod = findModule(text);

      // "Quiz: assessment timing is missing" -> no week set
      let m = text.match(/^(.*?):\s*assessment timing is missing/i);
      if (m) {
        const name = tidyName(mod ? m[1].replace(new RegExp(escapeRegex(mod), "i"), "") : m[1]);
        if (name) group(mod || "General").noTiming.add(name);
        return;
      }
      // "Quiz: assessment details are incomplete" -> missing details
      m = text.match(/^(.*?):\s*assessment details are incomplete/i);
      if (m) {
        const name = tidyName(mod ? m[1].replace(new RegExp(escapeRegex(mod), "i"), "") : m[1]);
        if (name) group(mod || "General").noDetails.add(name);
        return;
      }
      // skip vague lines that repeat what we already show
      if (/obtain specific scheduling|additional assessment detail/i.test(text)) return;
      // keep only things the student can act on (confirm / verify / check ...)
      if (/^(confirm|verify|check|clarify|ask|make sure)\b/i.test(text)) {
        group(mod || "General").notes.add(sentence(text));
      }
    });

    // 4) add a note if a module's weightage does not add up yet
    (data.coverage || []).forEach((c) => {
      if (c.complete === false && c.module_name) {
        const known = Math.round((Number(c.known_weightage_percent) || 0) * 10) / 10;   // round to 1 decimal
        group(c.module_name).notes.add(`Only ${known}% of the grade is filled in so far. Add the remaining weightage.`);
      }
    });

    // 5) turn each bucket into plain-language lines
    const entries = [];
    groups.forEach((g, name) => {
      const lines = [];
      if (g.noTiming.size) lines.push(`No week or date set yet for ${joinNames(g.noTiming)}.`);
      if (g.noDetails.size) lines.push(`Missing some details (like weightage) for ${joinNames(g.noDetails)}.`);
      g.notes.forEach((n) => lines.push(n));
      if (lines.length) entries.push({ name, lines });          // modules with no problems are skipped
    });
    // sort A-Z, "General" goes last
    entries.sort((a, b) => (a.name === "General") - (b.name === "General") || a.name.localeCompare(b.name));
    if (!entries.length) return;                                 // nothing to show -> stay hidden

    // 6) build the HTML: one big dropdown, with one small dropdown per module inside
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
    root.hidden = false;                                         // show it
  }
  buildAttention();

  // ================= PRIORITY GRID (modules = rows, weeks = columns, dot colour = priority) =================
  function buildPriorityGrid() {
    const table = document.getElementById("priority-grid");
    const dataEl = document.getElementById("schedule-data");
    const filterBar = document.getElementById("grid-filters");
    const tip = document.getElementById("dot-tip");
    if (!table || !dataEl) return;
    let data;
    try { data = JSON.parse(dataEl.textContent); } catch (_e) { return; }

    // ---- weeks: always show week 1 to the last week (14 by default) ----
    // backend may only send weeks from now onward, so we fill the missing ones
    const sent = new Map((data.timeline || []).map((w) => [Number(w.week), w]));   // week number -> week data
    if (!sent.size) return;
    const lastWeek = Math.max(Number(data.total_weeks) || 14, ...sent.keys());
    const weeks = Array.from({ length: lastWeek }, (_, i) => {
      const n = i + 1;
      const w = sent.get(n);
      return { number: n, label: (w && w.label) || `Week ${n}`, items: (w && w.assessments) || [] };   // items = [] for empty weeks
    });

    // ---- priority: High / Medium / Low ----
    // 1st choice: backend ranking score (top third = high, middle = medium, bottom = low)
    const key = (m, a) => `${m}||${a}`;                            // unique id for module + assessment
    const ranked = (data.ranking || [])
      .filter((r) => r.relative_score !== null && r.relative_score !== undefined && !isNaN(Number(r.relative_score)))
      .sort((a, b) => Number(b.relative_score) - Number(a.relative_score));   // biggest score first
    const level = new Map();
    ranked.forEach((r, i) => {
      const share = (i + 1) / ranked.length;                       // position from 0 to 1
      level.set(key(r.module_name, r.assessment_name), share <= 1 / 3 ? "high" : share <= 2 / 3 ? "medium" : "low");
    });
    function priorityOf(item) {
      // 1st: backend ranking
      const known = level.get(key(item.module_name, item.assessment_name));
      if (known) return known;
      // 2nd: weightage (30%+ high, 15%+ medium, else low)
      const w = item.weightage_percent;
      if (w !== null && w !== undefined && !isNaN(Number(w))) {
        return Number(w) >= 30 ? "high" : Number(w) >= 15 ? "medium" : "low";
      }
      // 3rd: guess from the assessment name, so every dot is always High/Medium/Low
      const text = `${item.assessment_name || ""} ${item.assessment_type || ""}`.toLowerCase();
      if (/exam|final|project|presentation|capstone|thesis/.test(text)) return "high";
      if (/quiz|test|midterm|mid-term|assignment|report|essay|case|practical/.test(text)) return "medium";
      return "low";
    }
    const order = { low: 1, medium: 2, high: 3 };                  // numbers so we can sort by priority
    const names = { high: "High priority", medium: "Medium priority", low: "Low priority" };   // for the hover card
    const chipNames = { high: "High", medium: "Medium", low: "Low" };                         // for filter buttons

    // ---- rows: one per module, in the order the student entered them ----
    const moduleOrder = [];
    const addModule = (n) => { if (n && !moduleOrder.includes(n)) moduleOrder.push(n); };
    (data.coverage || []).forEach((c) => addModule(c.module_name));
    (data.ranking || []).forEach((r) => addModule(r.module_name));
    weeks.forEach((w) => w.items.forEach((i) => addModule(i.module_name)));

    // ---- fill the grid data ----
    const cells = new Map();   // module -> week number -> list of dots
    const best = new Map();    // module -> its highest priority (used for sorting)
    const present = new Set(); // which priorities actually exist (for filter buttons)
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

    // ---- current state (changes when the user clicks) ----
    let sortMode = 0;                    // 0 = as entered, 1 = high first, 2 = low first
    const pickedPriorities = new Set();  // chosen priority filters (empty = show all)
    const pickedModules = new Set();     // chosen module filters (empty = show all)

    // ---- filter buttons ----
    function buildFilters() {
      if (!filterBar) return;
      // one button per priority that exists
      const prioChips = ["high", "medium", "low"].filter((p) => present.has(p)).map((p) =>
        `<button type="button" class="chip" data-prio="${p}" aria-pressed="false"><i class="dot p-${p}"></i>${chipNames[p]}</button>`).join("");
      // one button per module
      const modChips = moduleOrder.map((m) =>
        `<button type="button" class="chip" data-mod="${escapeHtml(m)}" aria-pressed="false">${escapeHtml(m)}</button>`).join("");
      filterBar.innerHTML =
        `<div class="filter-group"><span class="filter-label">Priority</span>${prioChips}</div>` +
        (moduleOrder.length > 1 ? `<div class="filter-group"><span class="filter-label">Module</span>${modChips}</div>` : "") +   // module filter only if 2+ modules
        `<button type="button" class="chip clear-chip" id="clear-filters" hidden>Clear filters</button>`;
    }
    // update which buttons look "pressed" + show/hide "Clear filters"
    function syncFilters() {
      if (!filterBar) return;
      filterBar.querySelectorAll("[data-prio]").forEach((c) => c.setAttribute("aria-pressed", pickedPriorities.has(c.dataset.prio)));
      filterBar.querySelectorAll("[data-mod]").forEach((c) => c.setAttribute("aria-pressed", pickedModules.has(c.dataset.mod)));
      const clear = filterBar.querySelector("#clear-filters");
      if (clear) clear.hidden = !(pickedPriorities.size || pickedModules.size);
    }

    // ---- draw the table (runs again after every filter / sort click) ----
    function render() {
      hideTip();
      // does this dot pass the priority filter?
      const showDot = (e) => !pickedPriorities.size || pickedPriorities.has(e.p);
      // rows: apply module filter, then drop rows that have no matching dot
      let rows = moduleOrder.filter((m) => !pickedModules.size || pickedModules.has(m));
      if (pickedPriorities.size) {
        rows = rows.filter((m) => [...cells.get(m).values()].some((list) => list.some(showDot)));
      }
      // sort rows by their highest priority
      if (sortMode === 1) rows.sort((a, b) => best.get(b) - best.get(a));
      if (sortMode === 2) rows.sort((a, b) => best.get(a) - best.get(b));

      // header row 1: "Module" sort button + "WKS" title
      const sortHint = ["Sort by priority", "Showing high priority first", "Showing low priority first"][sortMode];
      const head1 =
        `<tr><th class="mod-col" rowspan="2"><button type="button" class="sort-btn" id="sort-modules" title="${sortHint}" aria-label="${sortHint}">` +
        `<span>Module</span><span class="sort-arrows" aria-hidden="true">↑↓</span></button></th>` +
        `<th class="wks-label" colspan="${weeks.length}">WKS</th></tr>`;
      // header row 2: week numbers (current week is highlighted)
      const head2 = `<tr>${weeks.map((w) =>
        `<th title="${escapeHtml(w.label)}" class="${w.number === data.current_week ? "is-current-week" : ""}">${escapeHtml(w.number)}</th>`).join("")}</tr>`;
      // body: one row per module, one cell per week
      const body = rows.length ? rows.map((m) =>
        `<tr><th scope="row" class="mod-col">${escapeHtml(m)}</th>` +
        weeks.map((w) => {
          // dots in this cell: filtered, highest priority first
          const entries = (cells.get(m).get(w.number) || []).filter(showDot).sort((a, b) => order[b.p] - order[a.p]);
          const dots = entries.map((e) => {
            const weight = e.item.weightage_percent;
            const label = `${e.item.assessment_name}, ${m}, ${w.label}${weight !== null && weight !== undefined ? `, ${weight}%` : ""}, ${names[e.p]}`;   // screen reader text
            // data-* attributes store the info shown in the hover card
            return `<button type="button" class="pdot ${e.p}" aria-label="${escapeHtml(label)}"` +
              ` data-name="${escapeHtml(e.item.assessment_name)}" data-module="${escapeHtml(m)}" data-week="${escapeHtml(w.label)}"` +
              ` data-weight="${weight === null || weight === undefined ? "" : escapeHtml(weight)}" data-prio="${e.p}"></button>`;
          }).join("");
          return `<td class="${w.number === data.current_week ? "is-current-week" : ""}"><div class="cell-dots">${dots}</div></td>`;
        }).join("") + `</tr>`).join("")
        : `<tr><td class="no-match" colspan="${weeks.length + 1}">Nothing matches these filters.</td></tr>`;   // nothing left after filtering
      table.innerHTML = `<thead>${head1}${head2}</thead><tbody>${body}</tbody>`;
    }

    // ---- hover / tap card ----
    let pinned = null;   // the dot that was clicked/tapped (card stays open)
    function showTip(dot) {
      if (!tip) return;
      const weight = dot.dataset.weight;
      // fill the card with the dot's info
      tip.innerHTML =
        `<strong>${escapeHtml(dot.dataset.name)}</strong>` +
        `<span class="tip-weight">${weight !== "" ? `${escapeHtml(weight)}% of the grade` : "Weightage not set"}</span>` +
        `<span class="tip-meta">${escapeHtml(dot.dataset.module)} · ${escapeHtml(dot.dataset.week)}</span>` +
        `<span class="tip-prio"><i class="dot p-${dot.dataset.prio}"></i>${names[dot.dataset.prio]}</span>`;
      tip.hidden = false;
      // position the card above the dot (below it if there is no room above)
      const host = tip.parentElement.getBoundingClientRect();
      const r = dot.getBoundingClientRect();
      const width = tip.offsetWidth;
      let left = r.left - host.left + r.width / 2 - width / 2;          // centre on the dot
      left = Math.max(8, Math.min(left, host.width - width - 8));       // keep inside the panel
      tip.style.left = `${left}px`;
      tip.style.top = `${r.top - host.top - tip.offsetHeight - 10}px`;
      if (r.top - host.top - tip.offsetHeight - 10 < 0) tip.style.top = `${r.bottom - host.top + 10}px`;
    }
    function hideTip() {
      if (tip) tip.hidden = true;
      pinned = null;
    }

    // ---- events on the table ----
    // mouse hover shows the card, moving away hides it
    table.addEventListener("pointerover", (e) => {
      const dot = e.target.closest(".pdot");
      if (dot && e.pointerType === "mouse" && !pinned) showTip(dot);
    });
    table.addEventListener("pointerout", (e) => {
      if (e.target.closest(".pdot") && e.pointerType === "mouse" && !pinned) tip.hidden = true;
    });
    // keyboard focus (Tab key) also shows the card
    table.addEventListener("focusin", (e) => { const dot = e.target.closest(".pdot"); if (dot) showTip(dot); });
    table.addEventListener("focusout", (e) => { if (e.target.closest(".pdot") && !pinned) tip.hidden = true; });
    // click / tap
    table.addEventListener("click", (e) => {
      // sort button: cycle 0 -> 1 -> 2 -> 0
      if (e.target.closest("#sort-modules")) {
        sortMode = (sortMode + 1) % 3;
        render();
        return;
      }
      const dot = e.target.closest(".pdot");
      if (!dot) return;
      if (pinned === dot) { hideTip(); return; }    // tap same dot again = close
      showTip(dot);
      pinned = dot;                                  // keep the card open until you tap elsewhere
    });
    // click outside / press Esc / scroll the table = close the card
    document.addEventListener("click", (e) => { if (!e.target.closest(".pdot") && !e.target.closest("#dot-tip")) hideTip(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
    document.querySelector(".priority-scroll")?.addEventListener("scroll", hideTip);

    // ---- events on the filter buttons ----
    filterBar?.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      if (chip.id === "clear-filters") { pickedPriorities.clear(); pickedModules.clear(); }       // reset all
      else if (chip.dataset.prio) {
        // click again to un-pick
        pickedPriorities.has(chip.dataset.prio) ? pickedPriorities.delete(chip.dataset.prio) : pickedPriorities.add(chip.dataset.prio);
      } else if (chip.dataset.mod) {
        pickedModules.has(chip.dataset.mod) ? pickedModules.delete(chip.dataset.mod) : pickedModules.add(chip.dataset.mod);
      }
      syncFilters();
      render();
    });

    // ---- first draw ----
    buildFilters();
    syncFilters();
    render();
  }
  buildPriorityGrid();

  // ================= LIVE TIMER ON THE BUILD BUTTON =================
  // app.js updates #progress-elapsed (e.g. "3.2s"); we copy it onto the button
  const elapsed = document.getElementById("progress-elapsed");
  const timer = document.querySelector(".build-timer");
  const button = document.querySelector("#assessment-form button[type='submit']");
  if (elapsed && timer && button) {
    const sync = () => {
      timer.textContent = elapsed.textContent;   // copy the seconds
      timer.hidden = !button.disabled;           // show only while building (button is disabled)
    };
    // MutationObserver = runs a function whenever something on the page changes
    new MutationObserver(sync).observe(elapsed, { childList: true, characterData: true, subtree: true });
    new MutationObserver(sync).observe(button, { attributes: true, attributeFilter: ["disabled"] });
  }
})();