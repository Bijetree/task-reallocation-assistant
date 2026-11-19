from engine.config import DEFAULT_WEIGHTS, WORKLOAD_CAP
from engine.context import assignee_ids, skill_ids
from engine.models import Candidate, Factor

def _load_factor(task, member, weight):
    after = member["workload"] + task["duration"]
    value = max(0.0, 1-after/WORKLOAD_CAP)
    return Factor("load", value= value, weight= weight, note=f"workload would be {after} (now {member['workload']})")

def _fit_factor(task, member, weight):
    required = {s["skill_id"] for s in task["required_skills"]}
    if not required:
        return Factor("fit", value = 1.0, weight=weight, note="No specific skill required.")
    held = skill_ids(member) & required
    value = len(held)/len(required)
    return Factor("fit", value= value, weight= weight, note=f"holds {len(held)} out of the {len(required)} required skills.")

def _continuity_factor(ctx, task, member, weight):
    on_predecessor = False
    for dependency in task["dependencies"]:
        predecessor = ctx["tasks"].get(dependency["predecessor_id"])
        if predecessor is not None and member["member_id"] in assignee_ids(predecessor):
            on_predecessor = True
            break
    return Factor("continuity", value = 1.0 if on_predecessor else 0.0, weight= weight, note= "already works on a predecessor task" if on_predecessor else "no prior involvement")

def score_candidates(ctx, task_id, member, weights=None):
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    task = ctx["tasks"][task_id]
    factors = [
        _load_factor(task, member, weights["load"]),
        _fit_factor(task, member, weights["fit"]),
        _continuity_factor(ctx, task, member, weights["continuity"])
    ]
    return Candidate(member["member_id"], member["name"], factors, sum(f.contribution for f in factors))

def rank_candidates(ctx, task_id, members, weights = None):
    ranked = [score_candidates(ctx, task_id, m, weights) for m in members]
    return sorted(ranked, key=lambda c:(-c.score, c.member_id))

def explain(candidate):
    top = sorted(candidate.factors, key=lambda f:f.contribution, reverse=True)[:2]
    return f"{candidate.name} is recommended based on the strongest matching factors.\n" + "\n".join(
        f"- {f.name.title()}: {f.note}" for f in top)

def explain_margin(best, runner_up):
    other = {f.name: f.contribution for f in runner_up.factors}
    gains = {f.name: f.contribution - other.get(f.name, 0.0) for f in best.factors}
    if not gains:
        return ""
    name = max(gains, key=gains.get)
    if gains[name] <= 0:
        return ""
    note = next(f.note for f in best.factors if f.name == name)
    return f"ahead of {runner_up.name} mainly on {name} ({note})"
