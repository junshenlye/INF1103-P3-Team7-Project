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
{"relevant": true, "reason": "short explanation"}
"""


INTERPRETATION_PROMPT = """INTERPRETATION PASS
Build a complete, source-faithful assessment evidence memo for the named
module. Do not produce the final JSON structure yet.

Identify:
- every assessment, graded activity, and explicitly non-graded activity;
- multiplicity such as "x 10", weekly work, numbered items, and ranges;
- whether a weight belongs to one item, a group, a module part, or is unclear;
- parent-child relationships such as a project containing a proposal;
- explicit teaching weeks, recurring patterns, and missing schedule details;
- contradictions, vague statements, cropped content, and missing information;
- whether the visible source appears complete, partial, or unclear.

Do not invent individual weights, teaching weeks, or equal divisions.
Keep identically named source rows separate when they represent different
assessments. Limit follow-ups to uncertainty about assessment count, grading,
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
- Never copy a group-total weight onto every repeated assessment.
- Use record_role "group" for a non-schedulable parent total with children.
- A group record does not need its own schedule when its child assessments are
  schedulable.
- A missing or vague fact is a follow-up, not a reason to omit an assessment.
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
  "items": [
    {
      "title": "specific action",
      "assessment_id": "existing assessment ID or null",
      "module_title": "existing module title",
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
week within available_hours_per_week. Use null assessment_id only for a general
study habit that still belongs to an existing module.
"""


TRIMESTER_REVISION_PROMPT = """TRIMESTER REVISION PLAN
Create a Week 1-14 revision plan from the confirmed assessment data and study
preferences supplied below.

Return JSON only in this shape:
{
  "recommendation_type": "trimester_revision_plan",
  "summary": "short overview",
  "weeks": [
    {
      "week": 1,
      "focus": "short weekly focus",
      "items": [
        {
          "title": "specific revision action",
          "assessment_id": "existing assessment ID or null",
          "module_title": "existing module title",
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
available_hours_per_week. Suggestions must not become new assessment facts.
"""
