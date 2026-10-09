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
- explicit weeks, dates, recurring patterns, and missing schedule details;
- contradictions, vague statements, cropped content, and missing information;
- whether the visible source appears complete, partial, or unclear.

Do not invent individual weights, dates, teaching weeks, or equal divisions.
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
            "kind": "week | week_range | date | recurring | unknown",
            "week": "integer or null",
            "start_week": "integer or null",
            "end_week": "integer or null",
            "date": "string or null",
            "day": "string or null",
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
- Do not question an explicit week or date merely because its ordering looks
  unusual. Do not request rubrics or task instructions unless their absence
  prevents the assessment from being scheduled or weighted.
"""
