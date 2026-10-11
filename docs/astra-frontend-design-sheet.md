# Astra frontend design sheet

## Product vision

Design Stackplan as a calm trimester command centre, not another learning
management system. A student should understand the shape of the semester within
five seconds, see where evidence is uncertain, and turn assessments into a
realistic study plan without trusting AI blindly.

The frontend must be a separate application under `frontend/`. It consumes the
HTTP contract from `helpers/api_helper.py` and must not import Python code, read
PostgreSQL directly or depend on generated HTML.

## Experience principles

1. **Evidence before advice** — visually distinguish lecturer facts, student
   corrections and AI suggestions.
2. **Uncertainty is visible** — missing week or weight information is shown as
   a review task, never silently hidden.
3. **Semester first** — the main canvas shows workload across Weeks 1-14.
4. **Actions over dots** — assessments open into names, preparation work,
   rationale and status.
5. **Student control** — every AI recommendation can be edited, accepted or
   dismissed.
6. **Calm density** — complex data should feel clear rather than dashboard-heavy.

## Visual direction

Create a distinctive academic-planning system with warm paper-like surfaces,
deep ink typography and restrained semantic colour. Avoid a generic corporate
admin dashboard, excessive cards, neon gradients or an AI-chat-first layout.

Suggested semantic palette:

- confirmed fact: deep ink or navy;
- AI suggestion: violet/indigo;
- needs review: amber;
- high workload: terracotta;
- completed: muted green;
- unresolved week: patterned neutral rather than alarming red.

Use typography and spacing to establish hierarchy. Colour must not be the only
way status is communicated.

## Primary navigation

```text
Overview | Assessments | Study plan | Review | Settings
```

### Overview

- Trimester workload horizon across Weeks 1-14.
- Module lanes with assessment milestones.
- Current-week marker.
- High-load week explanation.
- Progress and unresolved-review summary.
- Quick transition between factual schedule and accepted study plan.

### Assessments

- Searchable assessment table grouped by module.
- Name, type, weight context, week, importance and confidence/review state.
- Source wording available on demand.
- Edit action creates a confirmed student revision.
- Group totals such as “Tutorials ×10 — 5% total” must remain explicit.

### Study plan

- Accepted work checklist and trimester revision plan.
- Weekly time budget versus planned hours.
- Completion controls.
- Clear explanation of why each task was recommended.
- Assessment link for every non-general task.

### Review

- Open source-coverage warnings and assessment follow-ups.
- Side-by-side current confirmed revision and new AI candidate.
- Accept candidate, retain confirmed version, or edit manually.
- Never use an ambiguous single “Fix with AI” action.

## Key interactions

### Create project

1. Name the trimester.
2. Upload module screenshots with module title and credit.
3. See per-module processing state.
4. Review partial success instead of losing the complete run.

### Resolve uncertainty

1. Select an amber review item.
2. See source wording, extracted value and consequence.
3. Enter a correction or mark it genuinely unknown.
4. Save a new confirmed revision.

### Generate a plan

1. Enter current week, weekly hours and preferred study days.
2. Choose checklist or trimester plan.
3. Preview AI candidate with weekly capacity checks.
4. Accept, edit or dismiss it.

## API contract

Use these endpoints as the integration boundary:

```text
GET    /health
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
POST   /api/projects/{project_id}/process
GET    /api/projects/{project_id}/schedule
PUT    /api/projects/{project_id}/modules/{module_title}
POST   /api/projects/{project_id}/modules/{module_title}/confirm
GET    /api/projects/{project_id}/recommendations
POST   /api/projects/{project_id}/recommendations
POST   /api/projects/{project_id}/recommendations/{id}/status
```

All responses use:

```json
{
  "payload": {},
  "errors": []
}
```

The upload endpoint accepts multipart form data:

- `modules`: JSON array containing `module_title`, `credit` and `file_field`;
- one image file for each declared `file_field`.

## Required states

Astra must design each screen for:

- initial empty state;
- processing;
- complete success;
- partial module success;
- complete failure;
- no confirmed revision;
- unresolved assessment;
- recommendation candidate;
- accepted recommendation;
- weekly capacity exceeded;
- API/database unavailable.

## Accessibility

- Full keyboard navigation.
- Visible focus states.
- Status text/icons in addition to colour.
- Accessible table alternative to the visual trimester timeline.
- Touch targets of at least 44 pixels.
- Reduced-motion support.
- Tooltips must not be the only place important information appears.

## Astra handoff task

Use a high-reasoning Astra design pass to produce:

1. information architecture;
2. desktop and mobile wireframes;
3. visual design system;
4. trimester overview prototype;
5. assessment review flow;
6. checklist and revision-plan flow;
7. API loading/error states;
8. reusable frontend component map.

Start against mock API fixtures derived from the contract. Do not change the
backend payload merely to make the mockup easier. If the design requires new
data, identify it explicitly as a proposed API contract change.
