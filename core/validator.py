from typing import Any


REQUIRED_PLAN_FIELDS = {"goal", "steps", "constraints"}
REQUIRED_STEP_FIELDS = {"id", "description", "files", "actions", "expected_output"}


class ValidationError(Exception):
    pass


def validate_plan(plan: Any) -> dict:
    if not isinstance(plan, dict):
        raise ValidationError("Plan must be a JSON object")

    missing = REQUIRED_PLAN_FIELDS - plan.keys()
    if missing:
        raise ValidationError(f"Plan missing required fields: {missing}")

    if not isinstance(plan["goal"], str) or not plan["goal"].strip():
        raise ValidationError("'goal' must be a non-empty string")

    if not isinstance(plan["steps"], list) or not plan["steps"]:
        raise ValidationError("'steps' must be a non-empty list")

    if not isinstance(plan["constraints"], list):
        raise ValidationError("'constraints' must be a list")

    normalized_steps = []
    for i, step in enumerate(plan["steps"]):
        if not isinstance(step, dict):
            raise ValidationError(f"Step {i} must be a JSON object")
        missing_step = REQUIRED_STEP_FIELDS - step.keys()
        if missing_step:
            raise ValidationError(f"Step {i} missing required fields: {missing_step}")
        normalized_steps.append({
            "id": int(step["id"]),
            "description": str(step["description"]).strip(),
            "files": [str(f).strip() for f in step["files"]] if isinstance(step["files"], list) else [],
            "actions": [str(a).strip() for a in step["actions"]] if isinstance(step["actions"], list) else [],
            "expected_output": str(step["expected_output"]).strip(),
            "depends_on": [int(d) for d in step["depends_on"]] if isinstance(step.get("depends_on"), list) else [],
        })

    return {
        "goal": plan["goal"].strip(),
        "steps": normalized_steps,
        "constraints": [str(c).strip() for c in plan["constraints"]],
    }

def validate_brainstorm(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValidationError('Brainstorm result must be a JSON object')
    for key in ('intent', 'approaches', 'ambiguities', 'recommended_approach'):
        if key not in data:
            raise ValidationError(f'Brainstorm missing field: {key}')
    return {
        'intent': str(data.get('intent', '')),
        'approaches': data.get('approaches', []),
        'ambiguities': [str(a) for a in data.get('ambiguities', [])],
        'recommended_approach': str(data.get('recommended_approach', '')),
    }

def validate_spec(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValidationError('Spec result must be a JSON object')
    for key in ('requirements', 'constraints', 'expected_outputs', 'out_of_scope'):
        if key not in data:
            raise ValidationError(f'Spec missing field: {key}')
    return {
        'requirements': [str(r) for r in data.get('requirements', [])],
        'constraints': [str(c) for c in data.get('constraints', [])],
        'expected_outputs': [str(o) for o in data.get('expected_outputs', [])],
        'out_of_scope': [str(s) for s in data.get('out_of_scope', [])],
    }