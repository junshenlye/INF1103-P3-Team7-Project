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


  // ================= SHARED: PRIORITY (High / Medium / Low) =================
  // returns a function priorityOf(item) -> "high" | "medium" | "low". used by the grid and the study plan
  function makePriorityFn(data) {
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
    return function priorityOf(item) {
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
    };
  }

  // any element with data-goto-tab="tab-id" switches to that tab (used by the "See what to prepare" buttons)
  document.addEventListener("click", (e) => {
    const go = e.target.closest("[data-goto-tab]");
    if (go) { activate(go.dataset.gotoTab); window.scrollTo({ top: 0, behavior: "smooth" }); }
  });

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
      if (!groups.has(name)) groups.set(name, { noTiming: new Set(), noDetails: new Set(), notes: new Set(), weight: null });
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
        group(c.module_name).weight = `Only ${known}% of the grade is filled in so far. Add the rest.`;   // kept separate so it is not merged away
      }
    });

    // 5) turn each bucket into SHORT plain-language lines (similar problems are merged into one line)
    // few names -> list them, many names -> just give the number
    function summarise(names, few, many) {
      const list = Array.from(names);
      return list.length <= 2 ? few(joinNames(list)) : many(list.length);
    }
    const entries = [];
    groups.forEach((g, name) => {
      const lines = [];
      if (g.noTiming.size) lines.push(summarise(g.noTiming,
        (n) => `Add the week or date for ${n}.`,
        (c) => `${c} assessments still need a week or date.`));
      if (g.noDetails.size) lines.push(summarise(g.noDetails,
        (n) => `Add the missing details (like weightage) for ${n}.`,
        (c) => `${c} assessments are missing some details, like weightage.`));
      if (g.weight) lines.push(g.weight);
      // AI notes: show one as-is, but merge several into one friendly line
      const notes = Array.from(g.notes);
      if (notes.length === 1) lines.push(notes[0]);
      else if (notes.length > 1) lines.push("A few other details are worth double-checking with your lecturer or course outline.");
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

    // ---- priority: High / Medium / Low (shared helper, see makePriorityFn above) ----
    const priorityOf = makePriorityFn(data);
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

  // ================= UPLOADED FILES PREVIEW (view what you picked, before building) =================
  // app.js fires a "change" event on the file input after browse OR drag-and-drop,
  // so one listener on the document covers both
  const IMAGE_EXT = /\.(png|jpe?g|webp|gif)$/i;
  const previewUrls = new WeakMap();      // input -> list of temporary urls (so we can free them later)

  // 1.5 MB / 230 KB style size text
  function niceSize(bytes) {
    return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB";
  }
  // short label for non-image files, e.g. "PDF", "DOCX"
  function extOf(name) {
    const m = name.match(/\.([a-z0-9]+)$/i);
    return m ? m[1].toUpperCase() : "FILE";
  }

  // draw the preview strip under one module's upload box
  function renderPreviews(input) {
    const block = input.closest(".module-entry");
    if (!block) return;
    // free the old temporary urls (stops the browser holding memory)
    (previewUrls.get(input) || []).forEach((u) => URL.revokeObjectURL(u));
    const urls = [];
    previewUrls.set(input, urls);

    let box = block.querySelector(".file-previews");
    if (!box) {                                            // create the strip the first time
      box = document.createElement("div");
      box.className = "file-previews";
      block.appendChild(box);
    }
    const files = Array.from(input.files);
    if (!files.length) { box.innerHTML = ""; box.hidden = true; return; }   // nothing uploaded -> hide
    box.hidden = false;

    box.innerHTML =
      `<div class="preview-title">Uploaded files (${files.length}) <small>· tap a file to view it</small></div>` +
      `<div class="preview-grid">` +
      files.map((f, i) => {
        const isImg = IMAGE_EXT.test(f.name) || f.type.startsWith("image/");
        let thumb;
        if (isImg) {
          const url = URL.createObjectURL(f);              // temporary link to the file on the user's computer
          urls.push(url);
          thumb = `<img src="${url}" alt="">`;
        } else {
          thumb = `<span class="file-badge">${escapeHtml(extOf(f.name))}</span>`;
        }
        return `<div class="preview-card">` +
          `<button type="button" class="preview-open" data-index="${i}" aria-label="View ${escapeHtml(f.name)}">${thumb}` +
          `<span class="preview-name">${escapeHtml(f.name)}</span><span class="preview-size">${niceSize(f.size)}</span></button>` +
          `<button type="button" class="preview-remove" data-index="${i}" aria-label="Remove ${escapeHtml(f.name)}">×</button>` +
          `</div>`;
      }).join("") + `</div>`;
  }

  // the pop-up viewer (created once, reused)
  let viewer = null;
  function closeViewer() {
    if (!viewer) return;
    viewer.hidden = true;
    viewer.querySelector(".viewer-body").innerHTML = "";   // stop any PDF/image from staying loaded
  }
  // show something in the pop-up. kind = "image", "pdf" or anything else
  function showInViewer(name, url, kind) {
    if (!viewer) {
      viewer = document.createElement("div");
      viewer.className = "file-viewer";
      viewer.hidden = true;
      viewer.innerHTML = `<div class="viewer-card" role="dialog" aria-modal="true" aria-label="File preview">` +
        `<div class="viewer-head"><strong class="viewer-name"></strong><button type="button" class="viewer-close" aria-label="Close">×</button></div>` +
        `<div class="viewer-body"></div></div>`;
      document.body.appendChild(viewer);
      // click the dark background or the × to close
      viewer.addEventListener("click", (e) => { if (e.target === viewer || e.target.closest(".viewer-close")) closeViewer(); });
    }
    viewer.querySelector(".viewer-name").textContent = name;
    const body = viewer.querySelector(".viewer-body");
    if (kind === "image") body.innerHTML = `<img src="${url}" alt="${escapeHtml(name)}">`;                  // image: show big
    else if (kind === "pdf") body.innerHTML = `<iframe src="${url}" title="${escapeHtml(name)}"></iframe>`;  // pdf: browser's own viewer
    else body.innerHTML = `<p class="viewer-note">This file type can't be previewed here, but it will still be used when you build your schedule.</p>`;
    viewer.hidden = false;
    viewer.querySelector(".viewer-close").focus();
  }
  // open a file the user just picked (still on their computer)
  function openViewer(file) {
    const url = URL.createObjectURL(file);
    if (viewer && viewer._url) URL.revokeObjectURL(viewer._url);   // free the previous temporary url
    const kind = IMAGE_EXT.test(file.name) || file.type.startsWith("image/") ? "image"
      : /\.pdf$/i.test(file.name) || file.type === "application/pdf" ? "pdf" : "other";
    showInViewer(file.name, url, kind);
    viewer._url = url;
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeViewer(); });

  // whenever a file input changes (browse or drop), redraw its previews
  document.addEventListener("change", (e) => {
    if (e.target.matches && e.target.matches("input[type='file']")) renderPreviews(e.target);
  });
  // click a preview card = open it, click × = remove just that file
  document.addEventListener("click", (e) => {
    const open = e.target.closest(".preview-open");
    const remove = e.target.closest(".preview-remove");
    if (!open && !remove) return;
    const block = (open || remove).closest(".module-entry");
    if (!block) return;                       // saved files (from the backend) are handled by loadUploads instead
    const input = block.querySelector("input[type='file']");
    const i = Number((open || remove).dataset.index);
    const files = Array.from(input.files);
    if (open) { openViewer(files[i]); return; }
    // remove: rebuild the file list without that file, then tell app.js (it listens for "change")
    const keep = new DataTransfer();
    files.forEach((f, n) => { if (n !== i) keep.items.add(f); });
    input.files = keep.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // ================= STUDY PLAN TAB (recommendations + to-do checklist) =================
  // idea: work BACKWARDS from each deadline. for every assessment we spread a few prep steps
  // between "this week" and the due week. nothing here comes from the backend except the
  // assessment list, so it works for any current week.

  // --- 1) the recipes: [position, id, text]. position 0 = start now, 1 = the due week ---
  // {n} is replaced with the assessment name. three recipes per type, chosen by how many weeks are left
  const PLANS = {
    work: {                    // assignment, report, essay, project, lab ...
      short: [[0, "brief", "Re-read the brief and rubric, then finish the main parts of {n}"], [1, "final", "Proofread, check the formatting, and submit {n} a day early if you can"]],
      medium: [[0, "brief", "Read the brief and rubric for {n}. Write down what is required"], [0.5, "draft", "Finish a full first draft of {n}. It doesn't have to be perfect"], [1, "final", "Check it against the rubric, proofread, and submit {n}"]],
      long: [[0, "brief", "Read the brief and rubric for {n}. Write down what is required"], [0.2, "plan", "Make an outline and list the sources or data you need"], [0.55, "draft", "Finish a full first draft"], [0.8, "review", "Check it against the rubric and get feedback from a friend or tutor"], [1, "final", "Proofread, check the formatting, and submit a day early"]],
    },
    exam: {
      short: [[0, "revise", "Go through your notes and the topics most likely to come up"], [1, "final", "Light revision, pack your ID and stationery, and get a good sleep"]],
      medium: [[0, "gather", "Collect the syllabus, lecture notes and past papers"], [0.5, "practice", "Do practice questions on your weakest topics"], [1, "final", "Light revision, pack your ID and stationery, and get a good sleep"]],
      long: [[0, "gather", "Collect the syllabus, lecture notes and past papers"], [0.3, "summary", "Make a one-page summary for each topic"], [0.6, "practice", "Do past-paper questions and mark yourself"], [0.85, "timed", "Do one full timed practice paper and fix the gaps"], [1, "final", "Light revision, pack your ID and stationery, and get a good sleep"]],
    },
    test: {                    // quiz, test, midterm
      short: [[0, "review", "Review what {n} covers and do a few practice questions"], [1, "final", "Quick recap of the key points and a good sleep"]],
      medium: [[0, "scope", "Check which topics {n} covers"], [0.6, "practice", "Go through your notes and do practice questions"], [1, "final", "Quick recap of the key points and a good sleep"]],
      long: [[0, "scope", "Check which topics {n} covers"], [0.4, "review", "Go through your notes and make short summary notes"], [0.75, "practice", "Do practice questions and fix the weak spots"], [1, "final", "Quick recap of the key points and a good sleep"]],
    },
    present: {
      short: [[0, "slides", "Finish your slides and practise {n} out loud"], [1, "final", "Do a final run-through and check your equipment"]],
      medium: [[0, "outline", "Outline what you'll say and what each slide shows"], [0.5, "rehearse", "Rehearse out loud and time yourself"], [1, "final", "Do a final run-through and check your equipment"]],
      long: [[0, "outline", "Outline what you'll say and what each slide shows"], [0.35, "slides", "Make the first version of your slides"], [0.7, "rehearse", "Rehearse out loud, with a friend if you can"], [0.9, "timed", "Do a timed run-through and trim anything too long"], [1, "final", "Do a final run-through and check your equipment"]],
    },
    habit: {                   // participation, attendance ...
      short: [[0, "keep", "Attend and join in every week. Small marks add up"]],
      medium: [[0, "keep", "Attend and join in every week. Small marks add up"]],
      long: [[0, "keep", "Attend and join in every week. Small marks add up"]],
    },
  };

  // which recipe fits this assessment? (look at its name and type; order matters)
  function planType(item) {
    const t = `${item.assessment_name || ""} ${item.assessment_type || ""}`.toLowerCase();
    if (/participation|attendance|discussion|engagement|class contribution/.test(t)) return "habit";
    if (/present|pitch|demo/.test(t)) return "present";
    if (/exam|final/.test(t)) return "exam";
    if (/quiz|test|midterm|mid-term/.test(t)) return "test";
    return "work";
  }

  // --- 2) saved ticks (kept in this browser only) ---
  const TICKS_KEY = "stackplan-study-done";
  function loadTicks() { try { return JSON.parse(localStorage.getItem(TICKS_KEY)) || {}; } catch (_e) { return {}; } }
  function saveTicks(t) { try { localStorage.setItem(TICKS_KEY, JSON.stringify(t)); } catch (_e) { /* storage blocked: ticks just won't be remembered */ } }

  function buildStudyPlan() {
    const root = document.getElementById("study-root");
    const summary = document.getElementById("study-summary");
    const dataEl = document.getElementById("schedule-data");
    if (!root || !summary || !dataEl) return;
    let data;
    try { data = JSON.parse(dataEl.textContent); } catch (_e) { return; }

    const current = Number(data.current_week) || 1;                // "this week" (1 if the trimester has not started)
    const priorityOf = makePriorityFn(data);
    const ticks = loadTicks();
    let view = "week";                                              // "week" = Overview (this week only), "all" = By assessment
    const pickedPrio = new Set();                                   // priority filter on the By assessment view (empty = show all)

    // --- 3) turn each assessment into a plan: { item, due, span, priority, tasks[] } ---
    const plans = [];
    const noWeek = [];                                              // assessments with no week yet
    (data.ranking || []).forEach((r) => {
      const weeks = (r.occurrence_weeks || []).map(Number).filter((n) => n >= 1);   // real week numbers only
      if (!weeks.length && Number(r.due_week) >= 1) weeks.push(Number(r.due_week));
      if (!weeks.length) { noWeek.push(r); return; }
      const upcoming = weeks.filter((w) => w >= current);
      if (!upcoming.length) return;                                 // already finished, nothing to prepare
      // repeating things (weekly quizzes): prepare for the NEXT one. otherwise: the last week is the deadline
      const due = r.recurring ? Math.min(...upcoming) : Math.max(...weeks);
      const span = due - current;                                   // weeks left
      const type = planType(r);
      const priority = priorityOf(r);
      const bucket = span <= 1 ? "short" : span <= 3 ? "medium" : "long";
      let recipe = PLANS[type][bucket].slice();
      // high priority gets extra steps (only when there is time)
      if (type !== "habit" && priority === "high" && span >= 2) recipe.unshift([0, "block", "Block out study time for {n} in your calendar"]);
      if (type !== "habit" && priority === "high" && span >= 4) recipe.push([0.5, "ask", "Ask your lecturer or tutor about anything you're unsure of"]);
      const tasks = recipe.map(([pos, key, text], order) => ({
        id: `${r.module_name}|${r.assessment_name}|${key}`,         // same id every visit, so ticks are remembered
        week: current + Math.round(pos * span),                      // spread between now and the due week
        order,
        text: text.replace("{n}", r.assessment_name),
      })).sort((a, b) => a.week - b.week || a.order - b.order);
      plans.push({ item: r, due, span, priority, type, tasks, repeats: r.recurring ? weeks.filter((w) => w >= current) : [] });
    });
    // soonest deadline first, then the more important one
    const rank = { high: 3, medium: 2, low: 1 };
    plans.sort((a, b) => a.due - b.due || rank[b.priority] - rank[a.priority]);

    // other things due in the same week (for the "busy week" heads-up)
    plans.forEach((p) => {
      p.sameWeek = plans.filter((o) => o !== p && o.due === p.due && o.type !== "habit");
    });

    // --- 4) small text helpers ---
    const dueText = (p) => p.span <= 0 ? "Due this week" : p.span === 1 ? "Due next week" : `Due in ${p.span} weeks`;
    const dotName = { high: "High priority", medium: "Medium priority", low: "Low priority" };
    function headsUp(p) {
      if (!p.sameWeek.length || p.type === "habit") return "";
      const names = p.sameWeek.slice(0, 2).map((o) => `${o.item.module_name} ${o.item.assessment_name}`);
      const text = p.sameWeek.length === 1
        ? `Heads-up: ${names[0]} is also due in Week ${p.due}. Start a few days earlier.`
        : `Heads-up: Week ${p.due} is busy, with ${p.sameWeek.length} other assessments landing too (${names.join(", ")}${p.sameWeek.length > 2 ? "…" : ""}). Start early.`;
      return `<p class="study-note">${escapeHtml(text)}</p>`;
    }
    const taskHtml = (t) =>
      `<label class="todo${ticks[t.id] ? " is-done" : ""}"><input type="checkbox" data-task="${escapeHtml(t.id)}"${ticks[t.id] ? " checked" : ""}>` +
      `<span class="todo-box" aria-hidden="true"></span><span class="todo-text">${escapeHtml(t.text)}</span></label>`;
    const doneCount = (tasks) => tasks.filter((t) => ticks[t.id]).length;

    // --- 5) draw everything ---
    function render(focusId) {
      const all = plans.flatMap((p) => p.tasks);
      const thisWeek = all.filter((t) => t.week === current);
      const pct = all.length ? Math.round((doneCount(all) / all.length) * 100) : 0;

      // top card: progress bar + view switch
      summary.innerHTML =
        `<div class="study-progress"><div class="study-progress-text"><strong>${doneCount(all)} of ${all.length} tasks done</strong>` +
        `<span>This week: ${doneCount(thisWeek)} of ${thisWeek.length}</span></div>` +
        `<div class="progress-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct}%"></span></div></div>` +
        `<div class="study-controls"><div class="seg" role="group" aria-label="View">` +
        `<button type="button" class="seg-btn" data-view="week" aria-pressed="${view === "week"}">Overview</button>` +
        `<button type="button" class="seg-btn" data-view="all" aria-pressed="${view === "all"}">By assessment</button></div>` +
        `<button type="button" class="text-button" id="study-reset">Uncheck all</button></div>` +
        // one line that explains the view you are on
        `<p class="study-hint">${view === "week"
          ? `Overview: your to-dos for this week (Week ${current}). Switch to <strong>By assessment</strong> for the full plan.`
          : "By assessment: the full plan for each assessment, week by week. Pick a colour to focus on it."}</p>` +
        // red / yellow / green filter (only on the By assessment view)
        (view === "all" ? `<div class="study-filters"><span class="filter-label">Priority</span>` +
          ["high", "medium", "low"].map((p) => {
            const n = plans.filter((x) => x.priority === p).length;
            return n ? `<button type="button" class="chip" data-prio="${p}" aria-pressed="${pickedPrio.has(p)}"><i class="dot p-${p}"></i>${{ high: "High", medium: "Medium", low: "Low" }[p]} (${n})</button>` : "";
          }).join("") +
          (pickedPrio.size ? `<button type="button" class="chip clear-chip" id="study-clear-prio">Clear</button>` : "") + `</div>` : "");

      if (!plans.length) {
        root.innerHTML = `<div class="empty-schedule"><span>✓</span><h3>Nothing to prepare right now</h3><p>No upcoming assessments were found in your schedule.</p></div>`;
        return;
      }

      let html = "";
      if (view === "week") {
        // THIS WEEK: only the tasks for this week, grouped by assessment
        const groups = plans.map((p) => ({ p, tasks: p.tasks.filter((t) => t.week === current) })).filter((g) => g.tasks.length);
        html = groups.length ? groups.map(({ p, tasks }) =>
          `<article class="study-card prio-${p.priority}"><header class="study-head"><span class="pdot ${p.priority}" title="${dotName[p.priority]}"></span>` +
          `<div class="study-title"><strong>${escapeHtml(p.item.assessment_name)}</strong><span>${escapeHtml(p.item.module_name)}${p.item.weightage_percent != null ? ` · ${escapeHtml(p.item.weightage_percent)}%` : ""}</span></div>` +
          `<span class="due-chip">${dueText(p)} · Week ${p.due}</span></header>` +
          `<div class="todo-list">${tasks.map(taskHtml).join("")}</div></article>`).join("")
          : `<div class="empty-schedule"><span>🎉</span><h3>Nothing to prep this week</h3><p>You're clear for now. Tap <strong>By assessment</strong> to see what's coming.</p></div>`;
      } else {
        // BY ASSESSMENT: a card per assessment with its steps week by week
        const shown = plans.filter((p) => !pickedPrio.size || pickedPrio.has(p.priority));   // apply the colour filter
        html = shown.length ? shown.map((p) => {
          const byWeek = new Map();
          p.tasks.forEach((t) => { if (!byWeek.has(t.week)) byWeek.set(t.week, []); byWeek.get(t.week).push(t); });
          const done = doneCount(p.tasks);
          const allDone = done === p.tasks.length;
          return `<article class="study-card prio-${p.priority}${allDone ? " is-complete" : ""}"><header class="study-head"><span class="pdot ${p.priority}" title="${dotName[p.priority]}"></span>` +
            `<div class="study-title"><strong>${escapeHtml(p.item.assessment_name)}</strong><span>${escapeHtml(p.item.module_name)}${p.item.weightage_percent != null ? ` · ${escapeHtml(p.item.weightage_percent)}% of the grade` : ""}</span></div>` +
            `<span class="due-chip">${dueText(p)} · Week ${p.due}</span></header>` +
            (p.repeats.length > 1 ? `<p class="study-meta">Repeats in weeks ${p.repeats.join(", ")}. This plan is for the next one.</p>` : "") +
            headsUp(p) +
            Array.from(byWeek, ([w, tasks]) =>
              `<div class="week-group"><span class="week-tag${w === current ? " is-now" : ""}">${w === current ? "This week" : `Week ${w}`}</span>` +
              `<div class="todo-list">${tasks.map(taskHtml).join("")}</div></div>`).join("") +
            `<footer class="study-foot">${allDone ? "✓ All prepared" : `${done} of ${p.tasks.length} done`}</footer></article>`;
        }).join("") : `<div class="empty-schedule"><span>·</span><h3>Nothing in this colour</h3><p>Try another priority, or tap <strong>Clear</strong>.</p></div>`;
      }
      if (noWeek.length) {
        html += `<p class="study-meta">No week set yet for ${escapeHtml(noWeek.map((r) => `${r.module_name} ${r.assessment_name}`).join(", "))}, so we can't plan these yet.</p>`;
      }
      html += `<p class="study-meta">Your ticks are saved on this device and browser only.</p>`;
      root.innerHTML = html;
      if (focusId) {                                                // keep keyboard focus on the box that was just ticked
        const box = Array.from(root.querySelectorAll("[data-task]")).find((x) => x.dataset.task === focusId);
        if (box) box.focus({ preventScroll: true });
      }
    }

    // --- 6) clicks ---
    root.addEventListener("change", (e) => {                        // a checkbox was ticked / unticked
      const box = e.target.closest("[data-task]");
      if (!box) return;
      if (box.checked) ticks[box.dataset.task] = true; else delete ticks[box.dataset.task];
      saveTicks(ticks);
      render(box.dataset.task);
    });
    summary.addEventListener("click", (e) => {
      const seg = e.target.closest("[data-view]");
      if (seg) { view = seg.dataset.view; render(); return; }
      const chip = e.target.closest("[data-prio]");                // red / yellow / green filter
      if (chip) { pickedPrio.has(chip.dataset.prio) ? pickedPrio.delete(chip.dataset.prio) : pickedPrio.add(chip.dataset.prio); render(); return; }
      if (e.target.closest("#study-clear-prio")) { pickedPrio.clear(); render(); return; }
      if (e.target.closest("#study-reset") && window.confirm("Uncheck every task?")) {
        Object.keys(ticks).forEach((k) => delete ticks[k]);
        saveTicks(ticks);
        render();
      }
    });
    render();
  }
  buildStudyPlan();

  // ================= UPLOADED FILES: view, replace, delete =================
  // WHERE the files come from:
  //   1) the backend, if it has GET /api/uploads (best: works on every device)
  //   2) otherwise this browser's own storage (IndexedDB): a copy kept when the user presses Build
  // the dropdown is ALWAYS shown, so the page never breaks if neither has files
  const uploadsRoot = document.getElementById("uploads-root");
  const apiBase = document.body.dataset.apiBase || "";

  // ---- tiny IndexedDB helper (a database inside the browser that can hold files) ----
  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open("stackplan-files", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("files", { keyPath: "id" });   // first time: create the table
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  // run one action on the "files" table, e.g. dbDo("readonly", (t) => t.getAll())
  async function dbDo(mode, action) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("files", mode);
      const req = action(tx.objectStore("files"));
      tx.oncomplete = () => { db.close(); resolve(req && req.result); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    });
  }
  const dbAll = () => dbDo("readonly", (t) => t.getAll());
  const dbPut = (rec) => dbDo("readwrite", (t) => t.put(rec));
  const dbDelete = (id) => dbDo("readwrite", (t) => t.delete(id));
  const newId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  // ---- save a copy of the files when the user presses "Build my schedule" ----
  // status "pending" = just submitted. it becomes "saved" once the schedule page loads (build worked)
  // (capture = true makes this run BEFORE app.js handles the submit)
  const buildForm = document.getElementById("assessment-form");
  let pendingWork = Promise.resolve();     // the copy job, so the error handler below can wait for it
  buildForm?.addEventListener("submit", () => { pendingWork = savePending(); }, true);
  async function savePending() {
    try {
      const old = (await dbAll()).filter((r) => r.status === "pending");
      for (const r of old) await dbDelete(r.id);                 // forget an earlier failed attempt
      for (const block of buildForm.querySelectorAll(".module-entry")) {
        const name = (block.querySelector("[data-field='module_name']")?.value || "").trim().toUpperCase() || "Other";
        for (const f of block.querySelector("input[type='file']").files) {
          await dbPut({ id: newId(), module_name: name, credit_units: block.querySelector("[data-field='credit_units']")?.value || "",
                        filename: f.name, content_type: f.type, size: f.size,
                        uploaded_at: new Date().toISOString(), status: "pending", blob: f });
        }
      }
    } catch (_e) { /* storage blocked (e.g. private window): just skip, nothing breaks */ }
  }

  // if the build failed, app.js shows the red error box -> throw away the pending copies
  const failBox = document.getElementById("extraction-progress");
  if (failBox) {
    new MutationObserver(async () => {
      if (!failBox.classList.contains("is-failed")) return;
      await pendingWork;                                         // let the copy job finish first
      try { for (const r of (await dbAll()).filter((x) => x.status === "pending")) await dbDelete(r.id); } catch (_e) {}
    }).observe(failBox, { attributes: true, attributeFilter: ["class"] });
  }

  // ---- small helpers ----
  const fileUrl = (u) => u.url || `${apiBase}/api/uploads/${encodeURIComponent(u.id)}`;   // where to load the file from
  const isImage = (u) => (u.content_type || "").startsWith("image/") || IMAGE_EXT.test(u.filename || "");
  const isPdf = (u) => u.content_type === "application/pdf" || /\.pdf$/i.test(u.filename || "");
  const savedDate = (u) => {                                   // "9 Oct 2026"
    const d = new Date(u.uploaded_at);
    return isNaN(d) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  };

  let savedList = [];          // the files currently shown
  let usingBrowser = false;    // true when they come from this browser instead of the backend
  let tempUrls = [];           // temporary links for browser-stored files (freed on every redraw)

  // draw the dropdown contents. message = optional line on top (e.g. "File deleted")
  function renderUploads(message, isError) {
    if (!uploadsRoot) return;
    uploadsRoot.querySelector(".uploads-count").textContent =
      savedList.length ? `${savedList.length} file${savedList.length === 1 ? "" : "s"}` : "None yet";
    const body = uploadsRoot.querySelector(".uploads-body");
    const note = message ? `<p class="uploads-note${isError ? " is-error" : ""}" role="status">${escapeHtml(message)}</p>` : "";
    if (!savedList.length) {
      body.innerHTML = note + `<p class="uploads-empty">No uploaded files yet. Files you upload will show up here.</p>`;
      return;
    }
    const where = usingBrowser ? `<p class="uploads-where">These files are kept on this device and browser only.</p>` : "";
    // group by module, e.g. INF1103 -> [file, file], INF1104 -> [file]
    const byModule = new Map();
    savedList.forEach((u) => {
      const key = u.module_name || "Other";
      if (!byModule.has(key)) byModule.set(key, []);
      byModule.get(key).push(u);
    });
    body.innerHTML = note + where + Array.from(byModule, ([mod, files]) =>
      `<div class="uploads-group"><div class="uploads-module">${escapeHtml(mod)}</div><div class="preview-grid">` +
      files.map((u) => {
        const i = savedList.indexOf(u);                        // position in the full list (used when clicked)
        const thumb = isImage(u) ? `<img src="${fileUrl(u)}" alt="" loading="lazy">`
          : `<span class="file-badge">${escapeHtml(extOf(u.filename || ""))}</span>`;
        return `<div class="preview-card saved-card">` +
          `<button type="button" class="preview-open" data-saved="${i}" aria-label="View ${escapeHtml(u.filename)}">${thumb}` +
          `<span class="preview-name">${escapeHtml(u.filename)}</span><span class="preview-size">${escapeHtml(savedDate(u))}</span></button>` +
          `<div class="card-actions">` +
          `<button type="button" class="mini-btn" data-replace="${i}">Replace</button>` +
          `<button type="button" class="mini-btn danger" data-delete="${i}">Delete</button></div>` +
          `</div>`;
      }).join("") + `</div></div>`).join("");
  }

  // get the list: backend first, then this browser
  async function loadUploads(message, isError) {
    if (!uploadsRoot) return;
    tempUrls.forEach((u) => URL.revokeObjectURL(u));           // free the old temporary links
    tempUrls = [];
    let list = [];
    usingBrowser = false;
    try {
      const res = await fetch(`${apiBase}/api/uploads`, { headers: { Accept: "application/json" } });
      if (res.ok) {
        const data = await res.json();
        list = Array.isArray(data) ? data : (data.uploads || []);
      }
    } catch (_e) { /* no backend list: fall through to the browser copy */ }
    if (!list.length) {                                        // backend has nothing -> use this browser's copy
      try {
        let rows = await dbAll();
        // NO schedule on the server (fresh start, e.g. after restarting docker) -> forget old copies too
        if (document.body.dataset.hasSchedule === "false") {
          for (const r of rows) await dbDelete(r.id);
          rows = [];
          try { localStorage.removeItem(TICKS_KEY); } catch (_e) {}   // and the study-plan ticks
        }
        // a finished build (schedule exists) turns "pending" into "saved"
        if (document.body.dataset.hasSchedule === "true") {
          for (const r of rows.filter((x) => x.status === "pending")) { r.status = "saved"; await dbPut(r); }
        }
        // same file uploaded twice (same module, name and size) -> keep only the newest copy
        const sameKey = (r) => `${r.module_name}|${r.filename}|${r.size}`;
        const keep = new Map();
        rows.filter((r) => r.status === "saved").forEach((r) => {
          const old = keep.get(sameKey(r));
          if (!old) { keep.set(sameKey(r), r); return; }
          const newer = r.uploaded_at > old.uploaded_at ? r : old;
          const older = newer === r ? old : r;
          dbDelete(older.id);                                  // remove the older duplicate
          keep.set(sameKey(r), newer);
        });
        list = Array.from(keep.values()).sort((a, b) => a.uploaded_at < b.uploaded_at ? 1 : -1)
          .map((r) => { const url = URL.createObjectURL(r.blob); tempUrls.push(url); return { ...r, url, local: true }; });
        usingBrowser = list.length > 0;
      } catch (_e) { list = []; }
    }
    savedList = list;
    renderUploads(message, isError);
  }

  // ---- keep the SCHEDULE in step with the files ----
  // the schedule is worked out from the files, so after a delete / replace we send the files that are
  // left to the backend again (same as pressing Build my schedule) and reload to show the new schedule
  let busy = false;                                             // true while a rebuild is running (ignore clicks)
  async function rebuildSchedule() {
    const rows = (await dbAll()).filter((r) => r.status === "saved").sort((a, b) => a.uploaded_at < b.uploaded_at ? -1 : 1);
    if (!rows.length) return "empty";                           // no files left, nothing to build from
    const byModule = new Map();                                 // module -> { credit, files[] }
    rows.forEach((r) => {
      if (!byModule.has(r.module_name)) byModule.set(r.module_name, { credit: "", files: [] });
      const m = byModule.get(r.module_name);
      if (!m.credit && r.credit_units) m.credit = r.credit_units;
      m.files.push(r);
    });
    // same field names the normal form uses: module_count, module_name_0, credit_units_0, source_files_0 ...
    const form = new FormData();
    form.append("module_count", String(byModule.size));
    let i = 0;
    byModule.forEach((m, name) => {
      form.append(`module_name_${i}`, name);
      form.append(`credit_units_${i}`, m.credit);
      m.files.forEach((r) => form.append(`source_files_${i}`, new File([r.blob], r.filename, { type: r.content_type })));
      i += 1;
    });
    const res = await fetch(`${apiBase}/api/extractions`, { method: "POST", body: form });
    if (!res.ok) throw new Error(String(res.status));
    return "ok";
  }
  // run a change on this browser's copy, then rebuild the schedule from what is left
  async function changeAndRebuild(change, doneNote) {
    busy = true;
    uploadsRoot.classList.add("is-busy");
    try {
      await change();
      await loadUploads("Updating your schedule… this can take a minute.");
      const result = await rebuildSchedule();
      if (result === "empty") {
        await loadUploads("That was your last file, so there is nothing to build a schedule from. Add a file and press Build my schedule.");
      } else {
        try { sessionStorage.setItem("stackplan-note", doneNote); } catch (_e) {}   // shown after the page reloads
        window.location.assign("/");                           // reload = the new schedule appears
        return;
      }
    } catch (_e) {
      await loadUploads("Your file change is saved, but the schedule couldn't be updated. Press Build my schedule to try again.", true);
    }
    busy = false;
    uploadsRoot.classList.remove("is-busy");
  }

  // delete one file
  async function deleteSaved(u) {
    if (busy) return;
    if (u.local) {
      if (!window.confirm(`Delete "${u.filename}"? Your schedule will be rebuilt without it.`)) return;
      await changeAndRebuild(() => dbDelete(u.id), "File deleted and your schedule was updated.");
      return;
    }
    if (!window.confirm(`Delete "${u.filename}"? This can't be undone.`)) return;
    try {
      const res = await fetch(fileUrl(u), { method: "DELETE" });   // backend: DELETE /api/uploads/<id>
      if (!res.ok) throw new Error(String(res.status));
      await loadUploads("File deleted. Press Build my schedule to update your schedule.");
    } catch (_e) {
      renderUploads("Couldn't delete that file. Please try again.", true);
    }
  }
  // replace one file with a new one
  async function replaceSaved(u, newFile) {
    if (busy) return;
    if (u.local) {
      await changeAndRebuild(() => dbPut({ id: u.id, module_name: u.module_name, credit_units: u.credit_units, filename: newFile.name,
        content_type: newFile.type, size: newFile.size, uploaded_at: new Date().toISOString(), status: "saved", blob: newFile }),
        "File updated and your schedule was updated.");
      return;
    }
    try {
      const form = new FormData();
      form.append("file", newFile);                             // backend: PUT /api/uploads/<id>, new file in field "file"
      const res = await fetch(fileUrl(u), { method: "PUT", body: form });
      if (!res.ok) throw new Error(String(res.status));
      await loadUploads("File updated. Press Build my schedule to update your schedule.");
    } catch (_e) {
      renderUploads("Couldn't update that file. Please try again.", true);
    }
  }

  if (uploadsRoot) {
    // one hidden file picker, reused for every "Replace" button
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = "image/png,image/jpeg,image/webp,image/gif,application/pdf,.txt,.md,.csv,.json,.docx";
    picker.hidden = true;
    uploadsRoot.appendChild(picker);
    let replacing = null;                                      // which saved file the picker is for

    uploadsRoot.addEventListener("click", (e) => {
      if (busy && e.target.closest("[data-delete], [data-replace]")) return;
      const view = e.target.closest("[data-saved]");
      const del = e.target.closest("[data-delete]");
      const rep = e.target.closest("[data-replace]");
      if (view) {                                              // open in the pop-up viewer
        const u = savedList[Number(view.dataset.saved)];
        showInViewer(u.filename, fileUrl(u), isImage(u) ? "image" : isPdf(u) ? "pdf" : "other");
      } else if (del) {
        deleteSaved(savedList[Number(del.dataset.delete)]);
      } else if (rep) {
        replacing = savedList[Number(rep.dataset.replace)];
        picker.value = "";                                     // allow picking the same file twice
        picker.click();
      }
    });
    picker.addEventListener("change", () => {
      if (picker.files.length && replacing) replaceSaved(replacing, picker.files[0]);
    });
    let firstNote;                                             // a message left by the page before the reload
    try { firstNote = sessionStorage.getItem("stackplan-note") || undefined; sessionStorage.removeItem("stackplan-note"); } catch (_e) {}
    loadUploads(firstNote);                                    // first load
  }

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