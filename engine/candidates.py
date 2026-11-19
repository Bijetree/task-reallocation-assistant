from engine.context import assignee_ids, skill_ids

def eligible_candidates(ctx, task_id, leaving_member_id = None):
    """Work out who may fill a slot on a task.

    ctx: the snapshot from context.load_context().
    task_id: the task that needs someone.
    leaving_member_id: the member whose slot is being filled, or None for a task nobody is on yet.

    Returns (eligible, rejected, gap):
      eligible: list of member dicts who may take the slot;
      rejected: {member_id: human-readable reason}, for everyone who was ruled out for being
                unavailable or lacking a needed skill (used to explain a 'wait' decision);
      gap:      set of skill ids the newcomer must bring.

    The rules:
      - the member must be available;
      - the member must not already be on the task, and is not the person leaving;
      - the team (the people staying + the newcomer) must cover every required skill, so the
        newcomer only has to bring the skills the remaining people do not already have.
    """
    task = ctx["tasks"][task_id]
    required = { s["skill_id"] : s["name"] for s in task["required_skills"]}
    remaining = assignee_ids(task) - {leaving_member_id}

    covered = set()
    for member_id in remaining:
        covered |= skill_ids(ctx["members"][member_id])
    gap = set(required) - covered

    eligible, rejected = [], {}
    for member in ctx["members"].values():
        member_id = member["member_id"]
        if member_id == leaving_member_id or member_id in remaining:
            continue
        if not member["available"]:
            rejected[member_id] = f"{member['name']} is not available."
            continue
        missing = gap - skill_ids(member)
        if missing:
            names = ", ".join(sorted(required[s] for s in missing))
            rejected[member_id] = f"{member['name']} lacks {names}."
            continue
        eligible.append(member)
    return eligible, rejected, gap