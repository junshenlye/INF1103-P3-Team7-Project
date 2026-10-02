"""Add deterministic schedule weights to canonical AI assessment data."""


ALLOWED_ASSESSMENT_CLASSIFICATIONS = {
    "graded",
    "aggregate",
    "bonus",
    "ungraded",
    "uncertain",
}
ALLOWED_WEIGHTAGE_SCOPES = {
    "total",
    "per_occurrence",
    "unknown",
}


def validate_logic_input(ai_result):
    """Check only the AI fields required to calculate schedule weight."""
    errors = []

    if not isinstance(ai_result, dict):
        return ["AI result must be an object."]

    modules = ai_result.get("modules")
    if not isinstance(modules, list):
        return ["AI result modules must be a list."]

    for module_index, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            errors.append(f"Module {module_index} must be an object.")
            continue

        raw_credits = module.get("credit_units")
        credits_are_supplied = raw_credits is not None
        credits_are_numeric = type(raw_credits) in (int, float)
        if credits_are_supplied and not credits_are_numeric:
            errors.append(f"Module {module_index} credit units must be a number.")
        if credits_are_numeric and not 0 < raw_credits <= 60:
            errors.append(f"Module {module_index} credit units must be between 0 and 60.")

        assessments = module.get("assessments")
        if not isinstance(assessments, list):
            errors.append(f"Module {module_index} assessments must be a list.")
            continue

        for assessment_index, assessment in enumerate(assessments, start=1):
            reference = f"Module {module_index} assessment {assessment_index}"
            if not isinstance(assessment, dict):
                errors.append(f"{reference} must be an object.")
                continue

            classification = assessment.get("classification")
            if classification not in ALLOWED_ASSESSMENT_CLASSIFICATIONS:
                errors.append(f"{reference} has an invalid classification.")

            raw_weight = assessment.get("weightage_percent")
            weight_is_supplied = raw_weight is not None
            weight_is_numeric = type(raw_weight) in (int, float)
            if weight_is_supplied and not weight_is_numeric:
                errors.append(f"{reference} weightage must be a number.")
            if weight_is_numeric and not 0 <= raw_weight <= 100:
                errors.append(f"{reference} weightage must be between 0 and 100.")

            weightage_scope = assessment.get("weightage_scope")
            if weightage_scope not in ALLOWED_WEIGHTAGE_SCOPES:
                errors.append(f"{reference} has an invalid weightage scope.")

            recurring = assessment.get("recurring")
            if type(recurring) is not bool:
                errors.append(f"{reference} recurring value must be true or false.")

    return errors


def build_module_data(ai_result, calendar=None):
    """Add deterministic schedule fields to the extracted assessment facts."""
    contract_errors = validate_logic_input(ai_result)
    if contract_errors:
        error_text = "; ".join(contract_errors)
        raise ValueError(f"Logic Manager received invalid AI data: {error_text}")

    recess_weeks = []
    if isinstance(calendar, dict):
        supplied_recess_weeks = calendar.get("recess_weeks", [])
        if isinstance(supplied_recess_weeks, list):
            recess_weeks = supplied_recess_weeks

    output_modules = []
    for module in ai_result["modules"]:
        output_module = module.copy()
        credit_units = module.get("credit_units")
        output_assessments = []
        module_schedule_issues = []
        if credit_units is None:
            module_schedule_issues.append(
                "Add the module credit value so schedule weights can be calculated."
            )

        for assessment in module["assessments"]:
            output_assessment = assessment.copy()
            classification = assessment["classification"]
            weightage_percent = assessment.get("weightage_percent")

            schedule_weight = None
            assessment_has_weight = classification in {"graded", "bonus"}
            calculation_has_inputs = (
                weightage_percent is not None and credit_units is not None
            )
            if assessment_has_weight and calculation_has_inputs:
                schedule_weight = round(weightage_percent * credit_units, 4)

            schedule_weeks = []
            schedule_issues = []
            recurring = assessment["recurring"]
            weightage_scope = assessment["weightage_scope"]
            due_week = assessment.get("due_week")
            missing_information = assessment.get("missing_information", [])
            missing_text = " ".join(missing_information).lower()

            if classification == "uncertain" and "grade" not in missing_text:
                schedule_issues.append(
                    "Confirm whether this assessment contributes to the module grade."
                )
            if (
                assessment_has_weight
                and weightage_percent is None
                and "weight" not in missing_text
            ):
                schedule_issues.append("Confirm the assessment weightage.")

            if recurring:
                recurrence = assessment.get("recurrence")
                recurrence_weeks = []
                if isinstance(recurrence, dict):
                    recurrence_weeks = recurrence.get("weeks", [])
                if isinstance(recurrence_weeks, list):
                    for week in recurrence_weeks:
                        week_is_valid = type(week) is int and week > 0
                        week_is_recess = week in recess_weeks
                        week_is_new = week not in schedule_weeks
                        if week_is_valid and not week_is_recess and week_is_new:
                            schedule_weeks.append(week)
                recurrence_is_missing = not schedule_weeks
                recurrence_is_not_explained = (
                    "week" not in missing_text and "timing" not in missing_text
                )
                if recurrence_is_missing and recurrence_is_not_explained:
                    schedule_issues.append("Confirm the weeks for this recurring assessment.")
                if weightage_scope == "unknown":
                    schedule_issues.append("Confirm whether its weight is total or per occurrence.")
            elif type(due_week) is int and due_week > 0:
                schedule_weeks.append(due_week)
            else:
                due_timing_is_not_explained = (
                    "week" not in missing_text
                    and "date" not in missing_text
                    and "timing" not in missing_text
                )
                if due_timing_is_not_explained:
                    schedule_issues.append("Confirm the due week for this assessment.")

            occurrence_schedule_weight = None
            occurrence_weightage_percent = None
            schedule_has_weight = schedule_weight is not None
            assessment_has_weightage = weightage_percent is not None
            schedule_has_weeks = len(schedule_weeks) > 0
            if schedule_has_weight and schedule_has_weeks:
                if recurring and weightage_scope == "total":
                    occurrence_count = len(schedule_weeks)
                    raw_occurrence_weight = schedule_weight / occurrence_count
                    occurrence_schedule_weight = round(raw_occurrence_weight, 4)
                elif not recurring or weightage_scope == "per_occurrence":
                    occurrence_schedule_weight = schedule_weight
            if assessment_has_weightage and schedule_has_weeks:
                if recurring and weightage_scope == "total":
                    occurrence_count = len(schedule_weeks)
                    raw_occurrence_percent = weightage_percent / occurrence_count
                    occurrence_weightage_percent = round(raw_occurrence_percent, 4)
                elif not recurring or weightage_scope == "per_occurrence":
                    occurrence_weightage_percent = weightage_percent

            schedule_ready = (
                schedule_has_weeks
                and occurrence_schedule_weight is not None
                and not schedule_issues
            )

            output_assessment["schedule_weight"] = schedule_weight
            output_assessment["schedule_weeks"] = schedule_weeks
            output_assessment["occurrence_schedule_weight"] = occurrence_schedule_weight
            output_assessment["occurrence_weightage_percent"] = occurrence_weightage_percent
            output_assessment["schedule_issues"] = schedule_issues
            output_assessment["schedule_ready"] = schedule_ready
            output_assessments.append(output_assessment)

        output_module["assessments"] = output_assessments
        output_module["schedule_issues"] = module_schedule_issues
        output_modules.append(output_module)

    output_calendar = {"recess_weeks": recess_weeks}
    return {"calendar": output_calendar, "modules": output_modules}


def review_result(ai_result):
    """Return grouped AI failures without changing assessment data."""
    errors = []
    failures = ai_result.get("failures", [])
    successful_modules = ai_result.get("modules", [])
    result_status = "accepted"

    for failure in failures:
        module_name = failure.get("module_name") or "Unknown module"
        category = failure.get("category")
        message = failure.get("message") or "The module could not be processed."

        if category == "system_failure":
            result_status = "system_failure"
        if category == "rejected_input" and result_status != "system_failure":
            result_status = "rejected_input"

        errors.append(f"{module_name}: {message}")

    if failures and successful_modules:
        result_status = "partial_success"

    unique_errors = list(dict.fromkeys(errors))
    return result_status, unique_errors
