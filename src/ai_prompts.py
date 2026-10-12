"""Prompt templates used by the Qwen assessment pipeline.

The relevance prompt is a cheap gate. The interpretation prompt allows open
reasoning, and the normalization prompt converts that memo into predictable
assessment prototypes. Keeping prompts here prevents model instructions from
obscuring the procedural code in ``ai_manager.py``.
"""


RELEVANCE_PROMPT = """RELEVANCE GATE
Decide whether this image contains module assessment information such as
assignments, quizzes, tutorials, projects, tests, examinations, weightages,
deadlines, teaching weeks, or assessment relationships.

Return JSON only in this exact shape:
{"relevant": true, "detected_module_title": "visible module code or null", "reason": "short explanation"}

Read detected_module_title from the image itself. Do not copy the module name
from the request. Use null when no module code is visible.
"""


INTERPRETATION_PROMPT = """INTERPRETATION PASS
Build a complete, source-faithful assessment evidence memo for the named
module using every supplied image. Images may show different pages for the
same module, so reconcile them before drawing conclusions. Do not produce the
final JSON structure yet.

Identify:
- every assessment, graded activity, and explicitly non-graded activity;
- multiplicity such as "x 10", weekly work, numbered items, and ranges;
- whether a weight belongs to one item, a group, a module part, or is unclear;
- parent-child relationships such as a project containing a proposal;
- explicit teaching weeks, recurring patterns, and missing schedule details;
- each visible source row and whether its weight covers one task or several;
- contradictions, vague statements, cropped content, and missing information;
- whether the visible source appears complete, partial, or unclear.

Week 7 is a recess week. Do not place an assessment in Week 7 merely because
its bubble, arrow, or surrounding layout is close to the recess column. Record
Week 7 only when the source explicitly states Week 7 or unambiguously anchors
the assessment to that labelled column.

Do not invent individual weights, teaching weeks, or equal divisions.
Keep identically named source rows separate when they represent different
assessments. A point or bubble attached to one week is a single-week event;
use a range only when the source explicitly shows an activity spanning all
weeks in that range. The schedule raw value must quote or closely preserve
visible source wording; it must not contain a model-invented week or range.
Limit follow-ups to uncertainty about assessment count, grading,
weight, scheduling, hierarchy, source coverage, or another material assessment
fact. Do not speculate about delivery format or topics not mentioned. Finish
with explicit sections for SOURCE NOTES and FOLLOW-UPS.
"""


NORMALIZATION_PROMPT = """NORMALIZATION PASS
Convert the interpretation memo into JSON for a scheduling pipeline. Recheck
the image for omissions, but use the memo as the semantic foundation.

Return JSON only. Do not wrap it in Markdown. Use this exact shape:
{
  "source_coverage": {
    "status": "appears_complete | partial | unclear",
    "comment": "string or null"
  },
  "assessment_types": [
    {
      "type": "assignment | quiz | tutorial | project | test | exam | presentation | essay | participation | other",
      "group_weight_percent": "number or null",
      "group_weight_scope": "module | part | group | unknown",
      "group_weight_scope_name": "string or null",
      "assessments": [
        {
          "name": "singular base name",
          "count": 1,
          "record_role": "assessment | group",
          "weight_percent": "number or null",
          "weight_scope": "module | part | group | unknown",
          "weight_scope_name": "string or null",
          "schedule": {
            "kind": "week | week_range | recurring | unknown",
            "week": "integer or null",
            "start_week": "integer or null",
            "end_week": "integer or null",
            "raw": "source wording or null"
          },
          "parent_assessment": "parent name or null",
          "details": "string or null"
        }
      ]
    }
  ],
  "notes": ["factual, non-actionable string"],
  "follow_ups": [
    {
      "assessment": "assessment or group name, or null",
      "field": "unclear field name",
      "message": "question or clarification needed"
    }
  ]
}

Rules:
- Keep incomplete assessments and use null for unknown values.
- Use one prototype with count 10 for "Tutorials x 10". Local code expands it.
- Use separate count-1 prototypes for explicitly listed Quiz 1, Quiz 2, etc.
- If numbered assessments map to separate listed weeks, give each prototype
  its own week. Never copy the combined week list onto every prototype.
- Never copy a group-total weight onto every repeated assessment.
- Never add separate row weights into a type-level group total. If the source
  states 20% on each of two quiz rows, each quiz keeps its own 20% weight.
- When one source row gives one weight for several tasks, create a
  ``record_role: group`` prototype for that row and link its task prototypes
  with ``parent_assessment``. Preserve repeated task labels separately when
  they appear under different weighted rows.
- Use record_role "group" for a non-schedulable parent total with children.
- A group record does not need its own schedule when its child assessments are
  schedulable.
- A missing or vague fact is a follow-up, not a reason to omit an assessment.
- Week 7 is recess. Use Week 7 only when the source explicitly schedules the
  assessment there. Visual proximity to the recess column is not sufficient.
- schedule.raw must preserve visible source wording. When no schedule wording
  is visible and placement is ambiguous, use kind "unknown" and raw null.
- Preserve the source's weight context, such as "Part I".
- Use source capitalization for assessment names.
- Put factual statements in notes and unresolved questions in follow_ups.
- Notes must be relevant to grading or scheduling. Exclude lecturer names,
  slide numbers, table headings, recording details, and other visual metadata.
- Follow-ups must affect count, grading, weight, schedule, hierarchy, source
  coverage, or another material assessment fact. Do not speculate about
  delivery format, online versus in-person mode, or unmentioned topics.
- Do not question an explicit teaching week merely because its ordering looks
  unusual. Do not request rubrics or task instructions unless their absence
  prevents the assessment from being scheduled or weighted.
"""


WORK_CHECKLIST_PROMPT = """WORK CHECKLIST RECOMMENDATION
Create a practical student checklist from the confirmed assessment data and
study preferences supplied below.

Return JSON only in this shape:
{
  "recommendation_type": "work_checklist",
  "summary": "short overview",
  "highlights": [
    {
      "title": "short label",
      "suggestion": "one useful sentence"
    }
  ],
  "items": [
    {
      "title": "specific action",
      "assessment_id": "existing assessment ID or null",
      "module_title": "existing module title or null for all modules",
      "week": 1,
      "estimated_hours": 1.5,
      "priority": "high | medium | low",
      "reason": "why this action is useful"
    }
  ]
}

Use only assessment IDs, modules, weights and teaching weeks present in the
confirmed data. Recommendations may add preparation actions but must not invent
deadlines, marks or assessment facts. Keep the total estimated hours in each
week within available_hours_per_week. Treat available hours as a ceiling, not
a target: do not add filler work to use every hour. Use null assessment_id for
a general study habit. Use null module_title only when it applies across all
modules.
Week 7 is recess. Leave it empty unless an item is linked to an assessment that
the confirmed schedule explicitly places in Week 7.

Write like a practical senior student, not a report. Use plain, direct English.
Keep the summary to one sentence of at most 20 words. Provide 2-3 highlights;
each needs a 2-4 word title and a suggestion of at most 14 words. Return no
more than 12 actions and put the most useful actions first. Action titles must
start with a verb and stay under 8 words. Reasons must stay under 16 words and
must not repeat the title, weight or deadline.
Combine repetitive tutorial or lab advice instead of listing near-identical
actions. Avoid generic catch-up tasks unless there is a real workload gap.
"""


TRIMESTER_REVISION_PROMPT = """TRIMESTER REVISION PLAN
Create a Week 1-14 revision plan from the confirmed assessment data and study
preferences supplied below.

Return JSON only in this shape:
{
  "recommendation_type": "trimester_revision_plan",
  "summary": "short overview",
  "highlights": [
    {
      "title": "short label",
      "suggestion": "one useful sentence"
    }
  ],
  "weeks": [
    {
      "week": 1,
      "focus": "short weekly focus",
      "items": [
        {
          "title": "specific revision action",
          "assessment_id": "existing assessment ID or null",
          "module_title": "existing module title or null for all modules",
          "week": 1,
          "estimated_hours": 1.5,
          "priority": "high | medium | low",
          "reason": "why this action is useful"
        }
      ]
    }
  ]
}

Use Weeks 1-14 only. Use only assessment IDs, modules, weights and teaching
weeks present in the confirmed data. Start preparation before important work,
retain catch-up capacity, and keep each week's total within
available_hours_per_week. Available hours are a ceiling, not a target. Do not
fill a week simply to use its remaining hours. Suggestions must not become new
assessment facts. Use null assessment_id for a general study habit. Use null
module_title only when it applies across all modules.
Week 7 is recess. Leave it empty unless an item is linked to an assessment that
the confirmed schedule explicitly places in Week 7.

Write like a practical senior student, not a project report. Use plain, direct
English and avoid motivational filler. Keep the summary to one sentence of at
most 20 words. Provide 2-3 highlights; each needs a 2-4 word title and a
suggestion of at most 14 words. Include only weeks with a useful action and use
1-3 actions per included week, ordered by importance. Keep each focus under 8
words, each verb-led action title under 8 words, and each reason under 16 words.
Do not repeat the title, weight or deadline in the reason. Combine repetitive
tutorials or lab work into a simple routine instead of producing near-identical
actions every week. Avoid generic "study habit" or "catch-up" items unless the
confirmed workload leaves a clear need for one. A concise plan with unused
capacity is better than a full plan.
"""
