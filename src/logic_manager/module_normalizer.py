"""Translate source prototypes into validated domain modules."""

import math
import re
from .rules import *
from ..domain.module import Module


class ModuleNormalizer:
    def normalize(self, record):
        return Module.from_record(self.normalize_module_record(record))

    def module_codes_match(self, requested_title, detected_title):
        """Return whether a visible module code matches the submitted label.

        A source without a visible code can continue. When both labels contain a
        code such as INF1103, they must refer to the same module.
        """
        if not isinstance(detected_title, str) or not detected_title.strip():
            return True
        pattern = re.compile("\\b[A-Z]{2,}\\s*[-_]?\\s*\\d{3,}[A-Z]?\\b", re.IGNORECASE)
        requested_match = pattern.search(requested_title)
        detected_match = pattern.search(detected_title)
        if requested_match is None or detected_match is None:
            return True
        canonical = lambda value: re.sub("[^A-Z0-9]", "", value.upper())
        return canonical(requested_match.group()) == canonical(detected_match.group())

    def append_follow_up(self, follow_ups, assessment, field, message):
        """Append one soft comment unless its assessment and field already exist.

        Follow-ups remain module metadata; they never enter the hard-error list.
        """
        target = assessment.casefold() if isinstance(assessment, str) else None
        for follow_up in follow_ups:
            existing = follow_up.get("assessment")
            existing_target = existing.casefold() if isinstance(existing, str) else None
            if existing_target == target and follow_up.get("field") == field:
                return
        follow_ups.append(
            {"assessment": assessment, "field": field, "message": message}
        )

    def normalize_weight(self, value, assessment, field, follow_ups):
        """Return a numeric weight or ``None`` when the value is not usable.

        A malformed value is retained as a soft follow-up so the module can still
        continue through the pipeline.
        """
        if value is None or (type(value) in (int, float) and math.isfinite(value)):
            return value
        self.append_follow_up(
            follow_ups,
            assessment,
            field,
            "The source weight could not be represented as a number.",
        )
        return None

    def normalize_schedule(self, schedule, assessment, follow_ups, required=True):
        """Return a schedule dictionary with the fields Logic Manager expects.

        Invalid combinations become ``kind: unknown``. When ``required`` is false,
        an unknown schedule is allowed because structural group records need no
        calendar entry.
        """
        if not isinstance(schedule, dict):
            schedule = {}
        normalized = {
            "kind": schedule.get("kind", "unknown"),
            "week": schedule.get("week"),
            "start_week": schedule.get("start_week"),
            "end_week": schedule.get("end_week"),
            "raw": schedule.get("raw"),
        }
        for field in ("week", "start_week", "end_week"):
            if type(normalized[field]) is not int:
                normalized[field] = None
        if not isinstance(normalized["raw"], str):
            normalized["raw"] = None
        if normalized["kind"] not in SCHEDULE_KINDS:
            normalized["kind"] = "unknown"
        kind = normalized["kind"]
        if kind == "week" and type(normalized["week"]) is not int:
            normalized["kind"] = "unknown"
        elif kind == "week_range" and (
            type(normalized["start_week"]) is not int
            or type(normalized["end_week"]) is not int
        ):
            normalized["kind"] = "unknown"
        elif kind == "recurring" and (not isinstance(normalized["raw"], str)):
            normalized["kind"] = "unknown"
        if normalized["kind"] == "unknown" and required:
            self.append_follow_up(
                follow_ups,
                assessment,
                "schedule",
                "No complete schedulable teaching week or recurrence was stated.",
            )
        return normalized

    def make_assessment_id(self, module_title, assessment_type, position):
        """Return a stable ID from module, type and one-based group position.

        IDs are created locally so model wording cannot introduce random or unsafe
        identifiers into frontend relationships.
        """
        module_code = re.sub("[^A-Z0-9]+", "-", module_title.upper()).strip("-")
        type_code = re.sub("[^A-Z0-9]+", "-", assessment_type.upper()).strip("-")
        return f"{module_code}-{type_code or 'OTHER'}-{position:02d}"

    def prepare_follow_ups(self, raw_follow_ups):
        """Return deduplicated model follow-ups that match the metadata contract.

        Unknown fields, malformed entries and messages without text are ignored.
        """
        if not isinstance(raw_follow_ups, list):
            return []
        follow_ups = []
        for follow_up in raw_follow_ups:
            if not isinstance(follow_up, dict):
                continue
            field = follow_up.get("field")
            message = follow_up.get("message")
            assessment = follow_up.get("assessment")
            if field not in FOLLOW_UP_FIELDS or not isinstance(message, str):
                continue
            if not isinstance(assessment, str):
                assessment = None
            self.append_follow_up(follow_ups, assessment, field, message)
        return follow_ups

    def prepare_group_specs(self, raw_groups, follow_ups):
        """Return validated intermediate groups keyed by canonical assessment type.

        Groups of the same type are merged in source order. Conflicting group
        weights are cleared and recorded as a soft follow-up instead of guessed.
        """
        if not isinstance(raw_groups, list):
            raise ValueError("Normalization response has no assessment type list.")
        group_order = []
        group_specs = {}
        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                raise ValueError("Normalization response contains an invalid group.")
            raw_type = raw_group.get("type")
            prototypes = raw_group.get("assessments")
            if not isinstance(raw_type, str) or not isinstance(prototypes, list):
                raise ValueError("Normalization response contains an invalid group.")
            assessment_type = (
                re.sub("[^a-z0-9]+", "_", raw_type.lower()).strip("_") or "other"
            )
            assessment_type = TYPE_ALIASES.get(assessment_type, assessment_type)
            if assessment_type not in ASSESSMENT_TYPES:
                self.append_follow_up(
                    follow_ups,
                    raw_type,
                    "type",
                    "The assessment type was unclear and was classified as other.",
                )
                assessment_type = "other"
            group_weight = self.normalize_weight(
                raw_group.get("group_weight_percent"),
                assessment_type,
                "group_weight_percent",
                follow_ups,
            )
            group_scope = raw_group.get("group_weight_scope", "unknown")
            if group_scope not in WEIGHT_SCOPES:
                group_scope = "unknown"
            group_scope_name = raw_group.get("group_weight_scope_name")
            if not isinstance(group_scope_name, str):
                group_scope_name = None
            if assessment_type not in group_specs:
                group_order.append(assessment_type)
                group_specs[assessment_type] = {
                    "type": assessment_type,
                    "group_weight_percent": group_weight,
                    "group_weight_scope": group_scope,
                    "group_weight_scope_name": group_scope_name,
                    "prototypes": list(prototypes),
                }
                continue
            existing = group_specs[assessment_type]
            existing["prototypes"].extend(prototypes)
            if existing["group_weight_percent"] != group_weight:
                existing["group_weight_percent"] = None
                existing["group_weight_scope"] = "unknown"
                existing["group_weight_scope_name"] = None
                self.append_follow_up(
                    follow_ups,
                    assessment_type,
                    "group_weight_percent",
                    "Multiple conflicting group weights were returned for this type.",
                )
        return [group_specs[assessment_type] for assessment_type in group_order]

    def reconcile_numbered_week_ranges(self, assessment_types, follow_ups, notes):
        """Repair one safe model pattern and flag the remaining ambiguous ranges.

        Models sometimes copy a comma-separated list such as ``Week 2, Week 3``
        onto both ``Quiz 1`` and ``Quiz 2``. When numbered records, listed weeks
        and range length match exactly, source order gives an unambiguous one-to-one
        mapping. Other list-like ranges remain unchanged and receive a follow-up.
        """
        for group in assessment_types:
            shared_ranges = {}
            for assessment in group["assessments"]:
                schedule = assessment["schedule"]
                raw = schedule.get("raw")
                name_match = re.match(
                    "^(.*?)(?:\\s+|[-#])(\\d+)$", assessment["name"].strip()
                )
                is_list_wording = isinstance(raw, str) and re.search(
                    ",|\\band\\b|&", raw, re.IGNORECASE
                )
                if (
                    assessment["record_role"] != "assessment"
                    or schedule["kind"] != "week_range"
                    or (not name_match)
                    or (not is_list_wording)
                ):
                    continue
                start_week = schedule["start_week"]
                end_week = schedule["end_week"]
                stated_weeks = [int(value) for value in re.findall("\\d+", raw)]
                expected_weeks = list(range(start_week, end_week + 1))
                if stated_weeks != expected_weeks:
                    continue
                key = (
                    name_match.group(1).strip().casefold(),
                    start_week,
                    end_week,
                    raw.casefold(),
                )
                shared_ranges.setdefault(key, []).append(
                    (int(name_match.group(2)), assessment)
                )
            for (_, start_week, end_week, _), numbered in shared_ranges.items():
                numbered.sort(key=lambda item: item[0])
                numbers = [number for (number, _) in numbered]
                weeks = list(range(start_week, end_week + 1))
                numbers_are_consecutive = numbers == list(
                    range(numbers[0], numbers[0] + len(numbers))
                )
                if len(numbered) != len(weeks) or not numbers_are_consecutive:
                    continue
                placements = []
                for week, (_, assessment) in zip(weeks, numbered):
                    assessment["schedule"].update(
                        {
                            "kind": "week",
                            "week": week,
                            "start_week": None,
                            "end_week": None,
                        }
                    )
                    placements.append(f"{assessment['name']}—Week {week}")
                notes.append(
                    "Schedule normalized from a shared list of weeks: "
                    + "; ".join(placements)
                    + "."
                )
            for assessment in group["assessments"]:
                schedule = assessment["schedule"]
                raw = schedule.get("raw")
                if (
                    schedule["kind"] == "week_range"
                    and isinstance(raw, str)
                    and re.search("/|,|\\band\\b|&", raw, re.IGNORECASE)
                ):
                    self.append_follow_up(
                        follow_ups,
                        assessment["name"],
                        "schedule",
                        "The source lists more than one week; confirm whether this assessment is active across the range or occurs in one specific week.",
                    )

    def build_module_output(self, module_title, credit, normalized):
        """Convert normalized prototypes into one schedule-ready module.

        This local pass expands repeated work, protects group weights, creates IDs,
        links parent records and attaches soft comments. Invalid core structures
        raise ``ValueError`` so only that module is removed.
        """
        coverage = normalized.get("source_coverage")
        if not isinstance(coverage, dict):
            coverage = {}
        coverage_status = coverage.get("status", "unclear")
        if coverage_status not in COVERAGE_STATUSES:
            coverage_status = "unclear"
        coverage_comment = coverage.get("comment")
        if not isinstance(coverage_comment, str):
            coverage_comment = None
        source_coverage = {"status": coverage_status, "comment": coverage_comment}
        notes = normalized.get("notes")
        if not isinstance(notes, list):
            notes = []
        notes = [note for note in notes if isinstance(note, str)]
        follow_ups = self.prepare_follow_ups(normalized.get("follow_ups"))
        group_specs = self.prepare_group_specs(
            normalized.get("assessment_types"), follow_ups
        )
        assessment_types = []
        name_lookup = {}
        pending_parents = []
        for group_spec in group_specs:
            assessment_type = group_spec["type"]
            assessments = []
            position = 0
            for prototype in group_spec["prototypes"]:
                if not isinstance(prototype, dict):
                    raise ValueError("Normalization response contains an invalid item.")
                base_name = prototype.get("name")
                if not isinstance(base_name, str) or not base_name.strip():
                    raise ValueError("Normalization response contains an unnamed item.")
                base_name = base_name.strip()
                count = prototype.get("count", 1)
                if type(count) is not int or count < 1:
                    count = 1
                    self.append_follow_up(
                        follow_ups,
                        base_name,
                        "count",
                        "The number of occurrences was unclear; one was retained.",
                    )
                record_role = prototype.get("record_role", "assessment")
                if record_role not in RECORD_ROLES:
                    record_role = "assessment"
                weight = self.normalize_weight(
                    prototype.get("weight_percent"),
                    base_name,
                    "weight_percent",
                    follow_ups,
                )
                weight_scope = prototype.get("weight_scope", "unknown")
                if weight_scope not in WEIGHT_SCOPES:
                    weight_scope = "unknown"
                if count > 1 and group_spec["group_weight_percent"] is not None:
                    weight = None
                weight_scope_name = prototype.get("weight_scope_name")
                if not isinstance(weight_scope_name, str):
                    weight_scope_name = None
                parent_name = prototype.get("parent_assessment")
                if not isinstance(parent_name, str):
                    parent_name = None
                details = prototype.get("details")
                if not isinstance(details, str):
                    details = None
                follow_up_target = base_name
                schedule = self.normalize_schedule(
                    prototype.get("schedule"),
                    follow_up_target,
                    follow_ups,
                    required=record_role == "assessment",
                )
                if (
                    count > 1
                    and schedule["kind"] == "recurring"
                    and (
                        type(schedule["start_week"]) is not int
                        or type(schedule["end_week"]) is not int
                    )
                ):
                    self.append_follow_up(
                        follow_ups,
                        follow_up_target,
                        "schedule",
                        "The recurring pattern does not state the full occurrence range.",
                    )
                if (
                    weight is None
                    and group_spec["group_weight_percent"] is None
                    and (record_role == "assessment")
                ):
                    self.append_follow_up(
                        follow_ups,
                        follow_up_target,
                        "weight_percent",
                        "No assessment weight was stated.",
                    )
                for occurrence in range(1, count + 1):
                    position += 1
                    name = f"{base_name} {occurrence}" if count > 1 else base_name
                    assessment_id = self.make_assessment_id(
                        module_title, assessment_type, position
                    )
                    assessment = {
                        "assessment_id": assessment_id,
                        "name": name,
                        "record_role": record_role,
                        "occurrence_number": occurrence,
                        "occurrence_count": count,
                        "weight_percent": weight,
                        "weight_scope": weight_scope,
                        "weight_scope_name": weight_scope_name,
                        "schedule": dict(schedule),
                        "parent_assessment_id": None,
                        "details": details,
                    }
                    assessments.append(assessment)
                    name_lookup.setdefault(name.casefold(), []).append(assessment_id)
                    pending_parents.append((assessment, parent_name))
            group = {
                "type": assessment_type,
                "declared_count": len(assessments),
                "group_weight_percent": group_spec["group_weight_percent"],
                "group_weight_scope": group_spec["group_weight_scope"],
                "group_weight_scope_name": group_spec["group_weight_scope_name"],
                "assessments": assessments,
            }
            assessment_types.append(group)
            if (
                len(assessments) > 1
                and group["group_weight_percent"] is not None
                and all((item["weight_percent"] is None for item in assessments))
            ):
                self.append_follow_up(
                    follow_ups,
                    assessment_type,
                    "weight_percent",
                    "The group total is known, but individual weights are not stated.",
                )
        self.reconcile_numbered_week_ranges(assessment_types, follow_ups, notes)
        for assessment, parent_name in pending_parents:
            if parent_name is None:
                continue
            parent_ids = name_lookup.get(parent_name.casefold(), [])
            if len(parent_ids) == 1:
                assessment["parent_assessment_id"] = parent_ids[0]
            else:
                self.append_follow_up(
                    follow_ups,
                    assessment["name"],
                    "parent_assessment_id",
                    f"Parent assessment '{parent_name}' could not be linked uniquely.",
                )
        records_by_name = {}
        for group in assessment_types:
            for assessment in group["assessments"]:
                records_by_name.setdefault(assessment["name"].casefold(), []).append(
                    assessment
                )
        resolved_follow_ups = []
        for follow_up in follow_ups:
            assessment_name = follow_up.get("assessment")
            records = (
                records_by_name.get(assessment_name.casefold(), [])
                if isinstance(assessment_name, str)
                else []
            )
            schedule_is_resolved = (
                follow_up.get("field") == "schedule"
                and len(records) == 1
                and (
                    records[0]["record_role"] == "group"
                    or records[0]["schedule"]["kind"] == "week"
                    or (
                        records[0]["schedule"]["kind"] == "recurring"
                        and type(records[0]["schedule"]["start_week"]) is int
                        and (type(records[0]["schedule"]["end_week"]) is int)
                    )
                )
            )
            if not schedule_is_resolved:
                resolved_follow_ups.append(follow_up)
        follow_ups = resolved_follow_ups
        if not assessment_types:
            self.append_follow_up(
                follow_ups,
                None,
                "assessment_types",
                "No schedulable assessments could be extracted from this source.",
            )
        if coverage_status != "appears_complete":
            self.append_follow_up(
                follow_ups,
                None,
                "source_coverage",
                coverage_comment or "The visible assessment source may be incomplete.",
            )
        for follow_up in follow_ups:
            assessment_name = follow_up.get("assessment")
            assessment_ids = (
                name_lookup.get(assessment_name.casefold(), [])
                if isinstance(assessment_name, str)
                else []
            )
            follow_up["assessment_id"] = (
                assessment_ids[0] if len(assessment_ids) == 1 else None
            )
        return {
            "module_title": module_title,
            "credit": credit,
            "source_coverage": source_coverage,
            "assessment_types": assessment_types,
            "notes": notes,
            "follow_ups": follow_ups,
        }

    def normalize_module_record(self, module):
        """Validate one parsed AI record and return its final module structure."""
        if not isinstance(module, dict):
            raise ValueError("Module record must be a dictionary.")
        module_title = module.get("module_title")
        credit = module.get("credit")
        relevance = module.get("ai_relevance")
        ai_output = module.get("ai_output")
        if not isinstance(module_title, str) or not module_title.strip():
            raise ValueError("Module title is missing.")
        if type(credit) not in (int, float):
            raise ValueError("Credit value is invalid.")
        if (
            not isinstance(relevance, dict)
            or type(relevance.get("relevant")) is not bool
        ):
            raise ValueError("AI relevance response is invalid.")
        if relevance["relevant"] is not True:
            reason = relevance.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                reason = "The source is not assessment-related."
            raise ValueError(reason)
        detected_module = relevance.get("detected_module_title")
        if not self.module_codes_match(module_title, detected_module):
            raise ValueError(
                f"Uploaded evidence appears to belong to {detected_module}."
            )
        if not isinstance(ai_output, dict):
            raise ValueError("AI output is not a structured object.")
        return self.build_module_output(module_title, credit, ai_output)
