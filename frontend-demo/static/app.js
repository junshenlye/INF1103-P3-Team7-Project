const form = document.querySelector("#assessment-form");
const moduleList = document.querySelector("#module-list");
const moduleTemplate = document.querySelector("#module-template");
const addModuleButton = document.querySelector("#add-module");
const moduleCount = document.querySelector("#module-count");
const progressPanel = document.querySelector("#extraction-progress");
const progressStage = document.querySelector("#progress-stage");
const progressElapsed = document.querySelector("#progress-elapsed");
const progressMessage = document.querySelector("#progress-message");
const runtimePanel = document.querySelector("#runtime-panel");
const schedulerGrid = document.querySelector("#scheduler-grid");
const scheduleData = document.querySelector("#schedule-data");
const calendarData = document.querySelector("#calendar-data");
const workspaceTabs = Array.from(document.querySelectorAll("[data-view-target]"));
const workspaceViews = Array.from(document.querySelectorAll(".workspace-view"));
const apiBaseUrl = document.body.dataset.apiBase || window.location.origin;
const hasStoredData = document.body.dataset.hasStoredData === "true";

function showWorkspaceView(viewId) {
  workspaceTabs.forEach((tab) => {
    const isSelected = tab.dataset.viewTarget === viewId;
    tab.setAttribute("aria-selected", isSelected ? "true" : "false");
    tab.tabIndex = isSelected ? 0 : -1;
  });
  workspaceViews.forEach((view) => {
    view.hidden = view.id !== viewId;
  });
  sessionStorage.setItem("stackplanActiveView", viewId);
}

workspaceTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const viewId = tab.dataset.viewTarget;
    showWorkspaceView(viewId);
  });
});

const savedViewId = sessionStorage.getItem("stackplanActiveView");
const savedViewExists = workspaceViews.some((view) => view.id === savedViewId);
const scheduleCanOpen = hasStoredData || savedViewId !== "schedule-view";
const initialViewId = savedViewExists && scheduleCanOpen ? savedViewId : "module-eval-view";
showWorkspaceView(initialViewId);

function apiUrl(path) {
  return path.startsWith("http") ? path : `${apiBaseUrl}${path}`;
}

function renumberModules() {
  const entries = Array.from(moduleList.querySelectorAll(".module-entry"));
  entries.forEach((entry, index) => {
    entry.querySelector("[data-module-number]").textContent = index + 1;
    entry.querySelectorAll("[data-field]").forEach((field) => {
      field.name = `${field.dataset.field}_${index}`;
      if (field.dataset.field === "source_files") {
        field.id = `source-files-${index}`;
      }
    });
    entry.querySelector("[data-remove-module]").hidden = entries.length === 1;
  });
  moduleCount.value = entries.length;
}

function addModule() {
  moduleList.appendChild(moduleTemplate.content.cloneNode(true));
  renumberModules();
}

function renderFiles(zone) {
  const input = zone.querySelector("input[type='file']");
  const list = zone.querySelector(".file-list");
  list.replaceChildren();
  Array.from(input.files).forEach((file) => {
    const item = document.createElement("div");
    item.className = "file-pill";
    item.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
    list.appendChild(item);
  });
}

addModuleButton?.addEventListener("click", addModule);
moduleList?.addEventListener("click", (event) => {
  const remove = event.target.closest("[data-remove-module]");
  if (remove && moduleList.children.length > 1) {
    remove.closest(".module-entry").remove();
    renumberModules();
    return;
  }
});

moduleList?.addEventListener("change", (event) => {
  if (event.target.matches("input[type='file']")) renderFiles(event.target.closest("[data-drop-zone]"));
});

moduleList?.addEventListener("keydown", (event) => {
  const zone = event.target.closest("[data-drop-zone]");
  if (
    zone &&
    !event.target.matches("input[type='file']") &&
    (event.key === "Enter" || event.key === " ")
  ) {
    event.preventDefault();
    zone.querySelector("input[type='file']").click();
  }
});

["dragenter", "dragover", "dragleave", "drop"].forEach((name) => {
  moduleList?.addEventListener(name, (event) => {
    const zone = event.target.closest("[data-drop-zone]");
    if (!zone) return;
    event.preventDefault();
    zone.classList.toggle("is-dragging", name === "dragenter" || name === "dragover");
    if (name === "drop" && event.dataTransfer?.files.length) {
      const input = zone.querySelector("input[type='file']");
      try {
        const transfer = new DataTransfer();
        Array.from(event.dataTransfer.files).forEach((file) => transfer.items.add(file));
        input.files = transfer.files;
      } catch (_error) {
        input.files = event.dataTransfer.files;
      }
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
});

function resetSubmitButton() {
  const button = form?.querySelector("button[type='submit']");
  if (!button) return;
  button.disabled = false;
  button.querySelector("span:first-child").textContent = "Extract assessments";
}

function showProgressError(message) {
  progressPanel.hidden = false;
  progressPanel.classList.add("is-failed");
  progressStage.textContent = "Assessment data could not be created";
  progressMessage.textContent = message;
  resetSubmitButton();
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  renumberModules();
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.querySelector("span:first-child").textContent = "Extracting assessments…";
  progressPanel.hidden = false;
  progressPanel.classList.remove("is-failed");
  progressStage.textContent = "Interpreting assessment evidence";
  progressMessage.textContent = "Modules are being validated and interpreted.";
  const startedAt = Date.now();
  const timer = window.setInterval(() => {
    progressElapsed.textContent = `${((Date.now() - startedAt) / 1000).toFixed(1)}s`;
  }, 200);
  try {
    const response = await fetch(apiUrl("/api/extractions"), { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    window.clearInterval(timer);
    const lastRun = {
      runtime: payload.runtime,
      modelsUsed: payload.models_used,
      modelRuns: payload.model_runs,
      failures: payload.failures,
      extractedCount: payload.extracted_count,
      status: payload.status,
    };
    sessionStorage.setItem("stackplanLastRun", JSON.stringify(lastRun));
    if (!response.ok) {
      renderLastRun(lastRun);
      showProgressError(payload.errors?.[0] || "The assessment data could not be created.");
      return;
    }
    sessionStorage.setItem("stackplanActiveView", "schedule-view");
    window.location.assign("/");
  } catch (_error) {
    window.clearInterval(timer);
    showProgressError("The request could not reach the local server.");
  }
});

function formatRuntime(milliseconds) {
  if (typeof milliseconds !== "number") return "Not run";
  if (milliseconds < 1000) return `${milliseconds.toFixed(0)} ms`;
  return `${(milliseconds / 1000).toFixed(2)} s`;
}

function renderLastRun(lastRun) {
  if (!runtimePanel) return;

  const logsEmpty = document.querySelector("#logs-empty");
  if (logsEmpty) {
    logsEmpty.hidden = true;
  }

  const runtime = lastRun.runtime || {};
  const modelsUsed = Array.isArray(lastRun.modelsUsed) ? lastRun.modelsUsed : [];
  const modelRuns = Array.isArray(lastRun.modelRuns) ? lastRun.modelRuns : [];
  const failures = Array.isArray(lastRun.failures) ? lastRun.failures : [];
  const extractedCount = Number.isInteger(lastRun.extractedCount) ? lastRun.extractedCount : 0;

  document.querySelector("#runtime-total").textContent = formatRuntime(runtime.frontend_total_ms);
  document.querySelector("#runtime-io").textContent = formatRuntime(runtime.io_manager_ms);
  document.querySelector("#runtime-ai").textContent = formatRuntime(runtime.ai_manager_ms);
  document.querySelector("#runtime-logic").textContent = formatRuntime(runtime.logic_manager_ms);
  document.querySelector("#runtime-data").textContent = formatRuntime(runtime.data_manager_ms);
  document.querySelector("#runtime-count").textContent = `${extractedCount} assessments extracted · ${lastRun.status || "unknown status"}`;
  document.querySelector("#runtime-models").textContent = modelsUsed.length ? modelsUsed.join(" → ") : "No model names returned";

  const modelRunList = document.querySelector("#model-run-list");
  modelRunList.replaceChildren();
  modelRuns.forEach((run) => {
    const row = document.createElement("div");
    const label = document.createElement("strong");
    const detail = document.createElement("span");
    label.textContent = `${run.module_name} · ${run.stage}`;
    detail.textContent = `${run.model || "Pipeline"} · ${run.status} · ${formatRuntime(run.duration_ms)}`;
    row.append(label, detail);
    modelRunList.appendChild(row);
  });

  const warningPanel = document.querySelector("#runtime-warnings");
  const failureList = document.querySelector("#runtime-failure-list");
  failureList.replaceChildren();
  failures.forEach((failure) => {
    const item = document.createElement("li");
    const failureType = failure.failure_type || failure.category;
    item.textContent = `${failure.module_name} · ${failure.stage} · ${failureType}: ${failure.message}`;
    failureList.appendChild(item);
  });
  warningPanel.hidden = failures.length === 0;
  runtimePanel.hidden = false;
}

function renderScheduler(modules, calendar) {
  if (!schedulerGrid) return;

  const scheduledAssessments = [];
  const excludedAssessments = [];
  const rawExcludedKeys = localStorage.getItem("stackplanExcludedAssessments");
  let excludedKeys = [];
  if (rawExcludedKeys) {
    try {
      const parsedExcludedKeys = JSON.parse(rawExcludedKeys);
      if (Array.isArray(parsedExcludedKeys)) {
        excludedKeys = parsedExcludedKeys;
      }
    } catch (_error) {
      localStorage.removeItem("stackplanExcludedAssessments");
    }
  }
  const excludedKeySet = new Set(excludedKeys);
  const recessWeekValues = calendar && Array.isArray(calendar.recess_weeks) ? calendar.recess_weeks : [];
  const recessWeeks = new Set(recessWeekValues);
  let maximumWeek = 0;
  let maximumWeight = 0;

  modules.forEach((module) => {
    const assessments = Array.isArray(module.assessments) ? module.assessments : [];
    assessments.forEach((assessment) => {
      if (assessment.classification === "aggregate") return;
      if (assessment.schedule_ready !== true) return;

      const assessmentKey = `${module.module_name}::${assessment.name}`;
      if (excludedKeySet.has(assessmentKey)) {
        excludedAssessments.push({
          assessmentKey,
          moduleName: module.module_name,
          assessment,
        });
        return;
      }

      const scheduleWeeks = Array.isArray(assessment.schedule_weeks) ? assessment.schedule_weeks : [];
      const occurrenceScheduleWeight = assessment.occurrence_schedule_weight;
      scheduleWeeks.forEach((scheduledWeek) => {
        const schedulerItem = {
          assessmentKey,
          moduleName: module.module_name,
          creditUnits: module.credit_units,
          assessment,
          scheduledWeek,
          scheduleWeight: occurrenceScheduleWeight,
          weightagePercent: assessment.occurrence_weightage_percent,
        };
        scheduledAssessments.push(schedulerItem);
        maximumWeek = Math.max(maximumWeek, scheduledWeek);
        if (typeof occurrenceScheduleWeight === "number") {
          maximumWeight = Math.max(maximumWeight, occurrenceScheduleWeight);
        }
      });
    });
  });

  const assessmentsByWeek = new Map();
  scheduledAssessments.forEach((item) => {
    const scheduledWeek = item.scheduledWeek;
    const weekAssessments = assessmentsByWeek.get(scheduledWeek) || [];
    weekAssessments.push(item);
    assessmentsByWeek.set(scheduledWeek, weekAssessments);
  });

  assessmentsByWeek.forEach((weekAssessments) => {
    weekAssessments.sort((left, right) => {
      const leftWeight = typeof left.scheduleWeight === "number" ? left.scheduleWeight : -1;
      const rightWeight = typeof right.scheduleWeight === "number" ? right.scheduleWeight : -1;
      if (leftWeight !== rightWeight) return rightWeight - leftWeight;

      const leftName = `${left.moduleName} ${left.assessment.name}`;
      const rightName = `${right.moduleName} ${right.assessment.name}`;
      return leftName.localeCompare(rightName);
    });
  });

  schedulerGrid.replaceChildren();
  schedulerGrid.style.setProperty("--week-count", Math.max(maximumWeek, 1));
  for (let weekNumber = 1; weekNumber <= maximumWeek; weekNumber += 1) {
    const weekColumn = document.createElement("article");
    weekColumn.className = "scheduler-week";

    const weekHeader = document.createElement("header");
    const weekLabel = document.createElement("strong");
    const weekCount = document.createElement("span");
    const weekAssessments = assessmentsByWeek.get(weekNumber) || [];
    const isRecessWeek = recessWeeks.has(weekNumber);
    weekLabel.textContent = isRecessWeek ? `Week ${weekNumber} · Recess` : `Week ${weekNumber}`;
    weekCount.textContent = `${weekAssessments.length}`;
    weekHeader.append(weekLabel, weekCount);
    weekColumn.appendChild(weekHeader);

    const weekStack = document.createElement("div");
    weekStack.className = "scheduler-week-stack";
    if (weekAssessments.length === 0) {
      const emptyWeek = document.createElement("span");
      emptyWeek.className = "scheduler-empty-week";
      emptyWeek.textContent = "No deadline";
      weekStack.appendChild(emptyWeek);
    }

    weekAssessments.forEach((item) => {
      const assessment = item.assessment;
      const card = document.createElement("article");
      card.className = "assessment-card";

      const cardModule = document.createElement("small");
      const cardName = document.createElement("strong");
      const cardMeta = document.createElement("span");
      const excludeButton = document.createElement("button");
      const weightTrack = document.createElement("i");
      const weightFill = document.createElement("b");
      const scheduleWeight = item.scheduleWeight;
      const hasWeight = typeof scheduleWeight === "number";
      let visibleWeight = "Unknown";
      if (hasWeight) {
        const fixedScheduleWeight = scheduleWeight.toFixed(2);
        visibleWeight = Number(fixedScheduleWeight);
      }
      const occurrenceWeightage = item.weightagePercent;
      const hasOccurrenceWeightage = typeof occurrenceWeightage === "number";
      const totalWeightage = assessment.weightage_percent;
      let cardMetaText = `Weight missing · schedule weight ${visibleWeight}`;
      const weightageIsTotal = assessment.weightage_scope === "total";
      const weightageIsPerOccurrence = assessment.weightage_scope === "per_occurrence";
      if (assessment.recurring && weightageIsTotal && hasOccurrenceWeightage && typeof totalWeightage === "number") {
        const fixedOccurrenceWeightage = occurrenceWeightage.toFixed(2);
        const visibleOccurrenceWeightage = Number(fixedOccurrenceWeightage);
        cardMetaText = `≈${visibleOccurrenceWeightage}% weekly share · ${totalWeightage}% overall · weekly schedule weight ${visibleWeight}`;
      } else if (assessment.recurring && weightageIsPerOccurrence && hasOccurrenceWeightage) {
        cardMetaText = `${occurrenceWeightage}% each occurrence · schedule weight ${visibleWeight}`;
      } else if (hasOccurrenceWeightage) {
        cardMetaText = `${occurrenceWeightage}% · schedule weight ${visibleWeight}`;
      }
      let weightWidth = 0;
      if (hasWeight && maximumWeight > 0) {
        weightWidth = Math.max(5, scheduleWeight / maximumWeight * 100);
      }

      cardModule.textContent = `${item.moduleName} · ${assessment.type}`;
      cardName.textContent = assessment.name;
      cardMeta.textContent = cardMetaText;
      excludeButton.type = "button";
      excludeButton.className = "exclude-assessment";
      excludeButton.textContent = "Exclude";
      excludeButton.addEventListener("click", () => {
        excludedKeySet.add(item.assessmentKey);
        const updatedExcludedKeys = Array.from(excludedKeySet);
        const excludedText = JSON.stringify(updatedExcludedKeys);
        localStorage.setItem("stackplanExcludedAssessments", excludedText);
        renderScheduler(modules, calendar);
      });
      weightTrack.className = "assessment-weight-track";
      weightFill.style.width = `${weightWidth}%`;
      weightTrack.appendChild(weightFill);
      card.append(cardModule, cardName, cardMeta, weightTrack, excludeButton);
      weekStack.appendChild(card);
    });

    weekColumn.appendChild(weekStack);
    schedulerGrid.appendChild(weekColumn);
  }

  const summary = document.querySelector("#schedule-summary");
  const scheduledLabel = scheduledAssessments.length === 1 ? "item" : "items";
  summary.textContent = `${scheduledAssessments.length} scheduled ${scheduledLabel} · ${excludedAssessments.length} excluded`;
  summary.hidden = false;

  const schedulerScroll = document.querySelector("#scheduler-scroll");
  schedulerScroll.hidden = scheduledAssessments.length === 0;

  const excludedPanel = document.querySelector("#excluded-schedule");
  const excludedList = document.querySelector("#excluded-schedule-list");
  if (!excludedPanel || !excludedList) return;

  excludedList.replaceChildren();
  excludedAssessments.forEach((item) => {
    const excludedRow = document.createElement("div");
    const excludedName = document.createElement("span");
    const restoreButton = document.createElement("button");
    excludedName.textContent = `${item.moduleName} · ${item.assessment.name}`;
    restoreButton.type = "button";
    restoreButton.textContent = "Restore";
    restoreButton.addEventListener("click", () => {
      excludedKeySet.delete(item.assessmentKey);
      const updatedExcludedKeys = Array.from(excludedKeySet);
      const excludedText = JSON.stringify(updatedExcludedKeys);
      localStorage.setItem("stackplanExcludedAssessments", excludedText);
      renderScheduler(modules, calendar);
    });
    excludedRow.append(excludedName, restoreButton);
    excludedList.appendChild(excludedRow);
  });
  excludedPanel.hidden = excludedAssessments.length === 0;
}

function renderAssessmentChecklist(modules) {
  const checklistSection = document.querySelector("#assessment-checklist");
  const moduleTabs = document.querySelector("#module-tabs");
  const moduleTabPanels = document.querySelector("#module-tab-panels");
  const checklistCount = document.querySelector("#checklist-count");
  if (!checklistSection || !moduleTabs || !moduleTabPanels || !checklistCount) return;

  moduleTabs.replaceChildren();
  moduleTabPanels.replaceChildren();
  let unresolvedAssessmentCount = 0;
  let visibleModuleCount = 0;

  modules.forEach((module, moduleIndex) => {
    const unresolvedAssessments = [];
    const assessments = Array.isArray(module.assessments) ? module.assessments : [];
    assessments.forEach((assessment) => {
      if (assessment.classification === "aggregate") return;

      const issues = [];
      const extractedIssues = Array.isArray(assessment.missing_information) ? assessment.missing_information : [];
      extractedIssues.forEach((issue) => {
        if (typeof issue === "string" && issue.trim()) {
          issues.push(issue.trim());
        }
      });
      const scheduleIssues = Array.isArray(assessment.schedule_issues) ? assessment.schedule_issues : [];
      scheduleIssues.forEach((issue) => {
        if (typeof issue === "string" && issue.trim()) {
          issues.push(issue.trim());
        }
      });

      const uniqueIssues = Array.from(new Set(issues));
      if (uniqueIssues.length > 0) {
        unresolvedAssessments.push({ assessment, issues: uniqueIssues });
      }
    });

    const moduleIssues = Array.isArray(module.schedule_issues) ? module.schedule_issues : [];
    const moduleHasErrors = unresolvedAssessments.length > 0 || moduleIssues.length > 0;
    if (!moduleHasErrors) return;

    const isFirstModule = visibleModuleCount === 0;
    const tabId = `module-tab-${moduleIndex}`;
    const panelId = `module-panel-${moduleIndex}`;

    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "module-tab";
    tab.id = tabId;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", panelId);
    tab.setAttribute("aria-selected", isFirstModule ? "true" : "false");
    tab.textContent = `${module.module_name} (${unresolvedAssessments.length})`;
    moduleTabs.appendChild(tab);

    const modulePanel = document.createElement("section");
    modulePanel.className = "module-tab-panel";
    modulePanel.id = panelId;
    modulePanel.setAttribute("role", "tabpanel");
    modulePanel.setAttribute("aria-labelledby", tabId);
    modulePanel.hidden = !isFirstModule;

    if (moduleIssues.length > 0) {
      const moduleIssue = document.createElement("p");
      moduleIssue.className = "module-checklist-note";
      moduleIssue.textContent = moduleIssues.join(" ");
      modulePanel.appendChild(moduleIssue);
    }

    const assessmentList = document.createElement("div");
    assessmentList.className = "assessment-checklist-items";
    unresolvedAssessments.forEach((item) => {
      unresolvedAssessmentCount += 1;

      const assessment = item.assessment;
      const assessmentRow = document.createElement("article");
      const assessmentMarker = document.createElement("span");
      const assessmentDetails = document.createElement("div");
      const assessmentName = document.createElement("strong");
      const assessmentMeta = document.createElement("span");
      const weightage = typeof assessment.weightage_percent === "number" ? `${assessment.weightage_percent}%` : "Weight unknown";
      const recurrence = assessment.recurrence;
      const recurrenceHasRange = recurrence && (Number.isInteger(recurrence.start_week) || Number.isInteger(recurrence.end_week));
      let timing = "Timing unknown";
      if (Number.isInteger(assessment.due_week)) {
        timing = `Week ${assessment.due_week}`;
      } else if (assessment.recurring && recurrenceHasRange) {
        const startWeek = recurrence.start_week || "?";
        const endWeek = recurrence.end_week || "?";
        timing = `Weeks ${startWeek}–${endWeek}`;
      } else if (assessment.recurring) {
        timing = "Recurring";
      }

      assessmentRow.className = "needs-check";
      assessmentMarker.className = "checklist-marker";
      assessmentMarker.textContent = "○";
      assessmentName.textContent = assessment.name;
      assessmentMeta.className = "assessment-checklist-meta";
      assessmentMeta.textContent = `${assessment.type} · ${weightage} · ${timing}`;
      assessmentDetails.append(assessmentName, assessmentMeta);

      const issueList = document.createElement("ul");
      item.issues.forEach((issue) => {
        const checklistItem = document.createElement("li");
        checklistItem.textContent = issue;
        issueList.appendChild(checklistItem);
      });
      assessmentDetails.appendChild(issueList);

      assessmentRow.append(assessmentMarker, assessmentDetails);
      assessmentList.appendChild(assessmentRow);
    });

    modulePanel.appendChild(assessmentList);
    moduleTabPanels.appendChild(modulePanel);

    tab.addEventListener("click", () => {
      const tabs = moduleTabs.querySelectorAll(".module-tab");
      const panels = moduleTabPanels.querySelectorAll(".module-tab-panel");
      tabs.forEach((moduleTab) => {
        const selected = moduleTab === tab;
        moduleTab.setAttribute("aria-selected", selected ? "true" : "false");
      });
      panels.forEach((panel) => {
        panel.hidden = panel !== modulePanel;
      });
    });

    visibleModuleCount += 1;
  });

  const assessmentLabel = unresolvedAssessmentCount === 1 ? "assessment" : "assessments";
  const moduleLabel = visibleModuleCount === 1 ? "module" : "modules";
  checklistCount.textContent = `${unresolvedAssessmentCount} unresolved ${assessmentLabel} · ${visibleModuleCount} ${moduleLabel}`;
  checklistSection.hidden = visibleModuleCount === 0;
}

if (runtimePanel) {
  const lastRunText = sessionStorage.getItem("stackplanLastRun");
  if (!hasStoredData) {
    sessionStorage.removeItem("stackplanLastRun");
  } else if (lastRunText) {
    try {
      const lastRun = JSON.parse(lastRunText);
      renderLastRun(lastRun);
    } catch (_error) {
      sessionStorage.removeItem("stackplanLastRun");
    }
  }
}

if (scheduleData && calendarData) {
  try {
    const storedModules = JSON.parse(scheduleData.textContent);
    const storedCalendar = JSON.parse(calendarData.textContent);
    renderScheduler(storedModules, storedCalendar);
    renderAssessmentChecklist(storedModules);
  } catch (_error) {
    if (schedulerGrid) {
      schedulerGrid.textContent = "The stored assessment data could not be displayed.";
    }
  }
}

if (moduleList && moduleTemplate) addModule();
