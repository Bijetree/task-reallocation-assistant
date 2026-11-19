"""Interactive terminal interface for the task reallocation engine.

Run with ``python -m interface.cli`` from the project root.
"""

from __future__ import annotations

from engine import context, decisions, service, triggers
from db_operations import retrieve, update


LINE = "-" * 72


def _read_int(prompt: str, *, allow_blank: bool = False) -> int | None:
    while True:
        value = input(prompt).strip()
        if allow_blank and not value:
            return None
        try:
            number = int(value)
        except ValueError:
            print("Enter a whole number.")
            continue
        if number <= 0:
            print("Enter an ID greater than zero.")
            continue
        return number


def _choose(prompt: str, choices: dict[str, str]) -> str | None:
    """Return a selected key, or None when the user cancels with a blank line."""
    if not choices:
        print("There are no available choices.")
        return None
    for key, label in choices.items():
        print(f"  {key}: {label}")
    while True:
        answer = input(prompt).strip()
        if not answer:
            return None
        if answer in choices:
            return answer
        print("Choose one of: " + ", ".join(choices))


def _print_decision(decision: dict) -> None:
    print(f"Decision #{decision['decision_id']} — {decision['action']} ({decision['status']})")
    print(f"Task: {decision['task_id']}")
    if decision.get("member_id") is not None:
        print(f"Recommended member: {decision['member_id']}")
    print(f"Confidence: {decision.get('confidence', 0):.0%}")
    print(f"Reason: {decision.get('reason', '')}")
    if decision.get("question"):
        print(decision["question"])
    if decision.get("revisit_when"):
        print(f"Revisit when: {decision['revisit_when']}")
    for index, option in enumerate(decision.get("options") or [], start=1):
        print(f"  {index}. {option['name']} (score {option['score']:.3f})")
    if decision.get("alternatives"):
        print("Alternatives:")
        for option in decision["alternatives"]:
            print(f"  - {option['name']} (score {option['score']:.3f})")
    print(LINE)


def show_board() -> None:
    ctx = context.load_context()
    print("TEAM")
    for member in ctx["members"].values():
        availability = "available" if member["available"] else "unavailable"
        skills = ", ".join(skill["name"] for skill in member["skills"]) or "no listed skills"
        role = "lead" if member["role"] else "member"
        print(f"  #{member['member_id']} {member['name']} — {availability}, {role}, "
              f"workload {member['workload']} — {skills}")

    print("\nTASKS")
    for task in ctx["tasks"].values():
        assignees = ", ".join(a["name"] for a in task["assignees"]) or "unassigned"
        skills = ", ".join(s["name"] for s in task["required_skills"]) or "no specific skills"
        print(f"  #{task['task_id']} {task['name']} — {task['status']}; {assignees}; "
              f"duration {task['duration']}, priority {task['priority']}, slack {task['slack']}; "
              f"needs {skills}")
    if not ctx["tasks"]:
        print("  No tasks have been added yet.")
    print(LINE)


def recommend() -> None:
    tasks = context.load_context()["tasks"]
    if not tasks:
        print("There are no tasks to recommend for yet.")
        return
    task_choices = {str(tid): task["name"] for tid, task in tasks.items()}
    task_id = int(_choose("Task ID (blank to cancel): ", task_choices) or 0)
    if not task_id:
        return
    task = tasks[task_id]
    leaving_id = None
    if task["assignees"]:
        leaving_choices = {str(a["member_id"]): a["name"] for a in task["assignees"]}
        selected = _choose("Member to replace (blank for initial/additional allocation): ", leaving_choices)
        leaving_id = int(selected) if selected else None
    decision = service.recommend_task(task_id, leaving_id)
    _print_decision(decision)


def show_pending() -> None:
    pending = decisions.list_pending()
    if not pending:
        print("There are no pending decisions.")
        return
    for decision in pending:
        _print_decision(decision)


def resolve_decision() -> None:
    pending = decisions.list_pending()
    if not pending:
        print("There are no pending decisions to resolve.")
        return
    choices = {
        str(d["decision_id"]): f"#{d['decision_id']} — task #{d['task_id']}, {d['action']}"
        for d in pending
    }
    selected = _choose("Decision ID (blank to cancel): ", choices)
    if selected is None:
        return
    decision = decisions.get_decision(int(selected))
    _print_decision(decision)

    approvers = {str(mid): member["name"] for mid, member in context.load_context()["members"].items()
                 if member["role"]}
    approver_choice = _choose("Approver member ID (blank to cancel): ", approvers)
    if approver_choice is None:
        return
    approver_id = int(approver_choice)
    action = _choose("Choose action: [a]pprove, [r]eject, [c]ancel: ", {
        "a": "approve", "r": "reject", "c": "cancel"
    })
    if action in (None, "c"):
        return

    if action == "r":
        note = input("Optional note: ").strip() or None
        result = service.reject_decision(decision["decision_id"], approver_id, note=note)
    else:
        member_id = None
        if decision["action"] == "ask":
            options = decision.get("options") or []
            option_choices = {str(option["member_id"]): option["name"] for option in options}
            selected_member = _choose("Choose a suggested member ID (blank to cancel): ", option_choices)
            if selected_member is None:
                return
            member_id = int(selected_member)
        note = input("Optional note: ").strip() or None
        result = service.approve_decision(
            decision["decision_id"], approver_id, member_id=member_id, note=note
        )
    _print_decision(result)


def change_availability() -> None:
    members = context.load_context()["members"]
    choices = {str(mid): member["name"] for mid, member in members.items()}
    selected = _choose("Member ID (blank to cancel): ", choices)
    if selected is None:
        return
    member_id = int(selected)
    new_value = not members[member_id]["available"]
    update.update_member_availability(member_id, new_value)
    results = triggers.member_availability_changed(member_id)
    label = "available" if new_value else "unavailable"
    print(f"Updated {members[member_id]['name']} to {label}.")
    if isinstance(results, list):
        for decision in results:
            _print_decision(decision)
    elif results:
        _print_decision(results)
    else:
        print("No reallocation decisions were needed.")


def change_task_status() -> None:
    ctx = context.load_context()
    tasks = ctx["tasks"]
    if not tasks:
        print("There are no tasks yet.")
        return
    selected = _choose("Task ID (blank to cancel): ",
                       {str(tid): task["name"] for tid, task in tasks.items()})
    if selected is None:
        return
    task_id = int(selected)
    old_status = tasks[task_id]["status"]
    statuses = retrieve.get_all_statuses()
    status_choices = {str(row["status_id"]): row["definition"] for row in statuses}
    selected_status = _choose("New status ID (blank to cancel): ", status_choices)
    if selected_status is None:
        return
    new_status = status_choices[selected_status]
    if new_status == old_status:
        print("That task already has this status.")
        return
    update.update_task_status(task_id, int(selected_status))
    results = triggers.task_status_changed(task_id, old_status, new_status)
    print(f"Updated task #{task_id} to {new_status}.")
    for decision in results:
        _print_decision(decision)
    if not results:
        print("No follow-up allocation was needed.")


def unassign_member_from_task() -> None:
    ctx = context.load_context()
    tasks = {tid: task for tid, task in ctx["tasks"].items() if task["assignees"]}
    if not tasks:
        print("No tasks currently have assignees.")
        return
    selected_task = _choose("Task ID (blank to cancel): ",
                            {str(tid): task["name"] for tid, task in tasks.items()})
    if selected_task is None:
        return
    task_id = int(selected_task)
    task = tasks[task_id]
    selected_member = _choose("Assignee ID (blank to cancel): ",
                              {str(a["member_id"]): a["name"] for a in task["assignees"]})
    if selected_member is None:
        return
    update.unassign_member(task_id, int(selected_member))
    result = triggers.task_unassigned(task_id)
    print(f"Unassigned member from task #{task_id}.")
    if result:
        _print_decision(result)


def run_sweep() -> None:
    result = triggers.run_scheduled_sweep()
    print(f"Expired decisions: {result['expired']}")
    print("At-risk tasks: " + (", ".join(map(str, result["at_risk_task_ids"])) or "none"))
    if result["decisions"]:
        print("Generated or refreshed decisions:")
        for decision in result["decisions"]:
            _print_decision(decision)
    else:
        print("No new decisions were needed.")


def show_history() -> None:
    history = retrieve.get_all_history()
    if not history:
        print("There is no assignment history yet.")
        return
    for row in history:
        assignee = row["assignee_name"] or "former member"
        print(f"{row['created_at']} — {row['action']} {assignee} "
              f"{'on' if row['action'] == 'assigned' else 'from'} {row['task_name']} "
              f"(task #{row['task_id']}, decision {row['decision_id'] or 'manual'})")


def undo_allocation() -> None:
    completed = [
        decision for decision in decisions.list_decisions(limit=1000)
        if decision["status"] in ("approved", "executed_auto") and decision.get("plan")
    ]
    if not completed:
        print("There are no approved allocations that can be undone.")
        return
    selected = _choose(
        "Decision ID (blank to cancel): ",
        {str(d["decision_id"]): f"#{d['decision_id']} — task #{d['task_id']}, {d['status']}"
         for d in completed},
    )
    if selected is None:
        return
    approvers = {str(mid): member["name"] for mid, member in context.load_context()["members"].items()
                 if member["role"]}
    approver_choice = _choose("Approver member ID (blank to cancel): ", approvers)
    if approver_choice is None:
        return
    note = input("Optional note: ").strip() or None
    result = service.undo_decision(int(selected), int(approver_choice), note=note)
    _print_decision(result)




def _menu() -> None:
    print("\nTask Reallocation Assistant")
    print("1. View team and task board")
    print("2. Get a task recommendation")
    print("3. View pending decisions")
    print("4. Approve or reject a decision")
    print("5. Toggle a member's availability")
    print("6. Change a task's status")
    print("7. Unassign a member from a task")
    print("8. Run the scheduled sweep")
    print("9. View assignment history")
    print("10. Undo an approved allocation")
    print("0. Exit")


def main() -> None:
    service.initialize_service()
    actions = {
        "1": show_board,
        "2": recommend,
        "3": show_pending,
        "4": resolve_decision,
        "5": change_availability,
        "6": change_task_status,
        "7": unassign_member_from_task,
        "8": run_sweep,
        "9": show_history,
        "10": undo_allocation,
    }
    print("Task Reallocation Assistant")
    while True:
        _menu()
        choice = input("Select an option: ").strip()
        if choice == "0":
            print("Goodbye.")
            return
        action = actions.get(choice)
        if action is None:
            print("Choose a menu number from 0 to 10.")
            continue
        try:
            action()
        except (ValueError, KeyError) as exc:
            print(f"Unable to complete that action: {exc}")
        except KeyboardInterrupt:
            print("\nAction cancelled.")


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")


