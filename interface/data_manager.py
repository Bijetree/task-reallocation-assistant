"""Entity creation and maintenance window backed by db_operations."""
import tkinter as tk
from tkinter import messagebox, ttk
from db_operations import create, delete, retrieve, update
from engine import triggers


class DataManager(tk.Toplevel):
    def __init__(self, parent, on_change, on_decisions=None):
        super().__init__(parent)
        self.on_change = on_change
        self.on_decisions = on_decisions
        self.title("Data management")
        self.geometry("1050x700")
        self.minsize(900, 600)
        self.configure(bg="#F2F5F8")
        self.transient(parent)
        style = ttk.Style(self)
        style.configure("Manager.Treeview", rowheight=27, font=("Segoe UI", 9))
        style.configure("Manager.Treeview.Heading", font=("Segoe UI Semibold", 9), padding=7)
        heading = ttk.Frame(self, padding=(20, 18, 20, 8))
        heading.pack(fill="x")
        ttk.Label(heading, text="Data management", font=("Segoe UI Semibold", 19)).pack(anchor="w")
        ttk.Label(heading, text="Create, update, link, and remove project records.",
                  foreground="#617181").pack(anchor="w", pady=(3, 0))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(8, 18))
        self.build_team_tab()
        self.build_catalog_tab()
        self.build_tasks_tab()
        self.build_links_tab()
        self.build_history_tab()
        self.refresh()
        self.grab_set()

    def _tab(self, title):
        frame = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(frame, text=title)
        return frame

    def _table(self, parent, columns, headings, widths):
        holder = ttk.Frame(parent)
        tree = ttk.Treeview(holder, columns=columns, show="headings", selectmode="browse",
                            style="Manager.Treeview", height=12)
        for col, heading, width in zip(columns, headings, widths):
            tree.heading(col, text=heading)
            tree.column(col, width=width, minwidth=55,
                        anchor="w" if col in ("name", "skills", "assignees") else "center")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        holder.pack(fill="both", expand=True)
        return tree

    def _buttons(self, parent, actions):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(10, 0))
        for label, callback, primary in actions:
            ttk.Button(bar, text=label, command=callback,
                       style="Accent.TButton" if primary else "TButton").pack(side="left", padx=(0, 7))

    def _form(self, title, fields, submit, on_success=None):
        window = tk.Toplevel(self)
        window.title(title)
        window.transient(self)
        window.grab_set()
        window.resizable(False, False)
        body = ttk.Frame(window, padding=20)
        body.pack(fill="both", expand=True)
        variables, widgets, maps = {}, {}, {}
        for row, field in enumerate(fields):
            key, label = field["key"], field["label"]
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 16), pady=7)
            kind = field.get("kind", "text")
            if kind in ("text", "int"):
                var = tk.StringVar(value=str(field.get("default", "")))
                widget = ttk.Entry(body, textvariable=var, width=48)
                variables[key] = var
            elif kind in ("choice", "boolean"):
                var = tk.StringVar()
                options = field.get("options", [])
                labels = [item[0] for item in options]
                default = field.get("default")
                var.set(next((label for label, value in options if value == default), labels[0] if labels else ""))
                widget = ttk.Combobox(body, textvariable=var, values=labels, state="readonly", width=45)
                variables[key] = var
                maps[key] = {label: value for label, value in options}
            elif kind == "multi":
                options = field.get("options", [])
                widget = tk.Listbox(body, selectmode="extended", height=min(max(len(options), 3), 7),
                                    exportselection=False, relief="solid", borderwidth=1,
                                    font=("Segoe UI", 9), selectbackground="#D9E9F7")
                for index, (label, value) in enumerate(options):
                    widget.insert("end", label)
                    if value in field.get("selected", []):
                        widget.selection_set(index)
                widgets[key] = widget
                maps[key] = {label: value for label, value in options}
            widget.grid(row=row, column=1, sticky="ew", pady=6)
        buttons = ttk.Frame(body)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(14, 0))

        def save():
            try:
                data = {}
                for field in fields:
                    key, kind = field["key"], field.get("kind", "text")
                    if kind == "multi":
                        labels = [widgets[key].get(i) for i in widgets[key].curselection()]
                        data[key] = [maps[key][label] for label in labels]
                    elif kind in ("choice", "boolean"):
                        if variables[key].get() not in maps[key]:
                            raise ValueError(f"Choose a value for {field['label']}.")
                        data[key] = maps[key][variables[key].get()]
                    elif kind == "int":
                        try:
                            data[key] = int(variables[key].get())
                        except ValueError as exc:
                            raise ValueError(f"{field['label']} must be a whole number.") from exc
                    else:
                        data[key] = variables[key].get().strip()
                result = submit(data)
                window.destroy()
                self.refresh()
                self.on_change()
                decision_count = self.on_decisions(result) if self.on_decisions else 0
                if on_success:
                    on_success(result)
                elif not decision_count:
                    messagebox.showinfo(title, "The change was saved.", parent=self)
            except Exception as exc:
                messagebox.showerror("Unable to save", str(exc), parent=window)

        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=save).pack(side="right", padx=8)
        window.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - window.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - window.winfo_height()) // 2
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _selected_id(self, tree, label):
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("Select a record", f"Select a {label} first.", parent=self)
            return None
        return int(selection[0])

    @staticmethod
    def _clear(tree):
        for item in tree.get_children():
            tree.delete(item)

    def build_team_tab(self):
        tab = self._tab("Team members")
        self.member_tree = self._table(tab, ("id", "name", "availability", "role", "workload", "skills"),
            ("ID", "Name", "Availability", "Role", "Workload", "Skills"), (55, 145, 110, 75, 80, 300))
        self._buttons(tab, [("Create member", self.create_member, True), ("Edit name", self.edit_member, False),
            ("Add skill", self.add_member_skill, False), ("Remove skill", self.remove_member_skill, False),
            ("Delete member", self.remove_member, False)])

    def build_catalog_tab(self):
        tab = self._tab("Skills and statuses")
        columns = ttk.Frame(tab)
        columns.pack(fill="both", expand=True)
        left = ttk.LabelFrame(columns, text="Skills", padding=10)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.skill_tree = self._table(left, ("id", "name"), ("ID", "Skill"), (65, 250))
        self._buttons(left, [("Create skill", self.create_skill, True), ("Rename", self.edit_skill, False), ("Delete", self.remove_skill, False)])
        right = ttk.LabelFrame(columns, text="Task statuses", padding=10)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.status_tree = self._table(right, ("id", "name"), ("ID", "Status"), (65, 250))
        self._buttons(right, [("Create status", self.create_status, True), ("Rename", self.edit_status, False), ("Delete", self.remove_status, False)])

    def build_tasks_tab(self):
        tab = self._tab("Tasks")
        self.tasks_tree = self._table(tab, ("id", "name", "duration", "status", "priority", "slack", "assignees", "skills"),
            ("ID", "Task", "Duration", "Status", "Priority", "Slack", "Assignees", "Required skills"),
            (50, 175, 75, 100, 70, 65, 165, 190))
        self._buttons(tab, [("Create task", self.create_task, True), ("Edit selected task", self.edit_task, False),
                            ("Delete selected task", self.remove_task, False)])

    def build_links_tab(self):
        tab = self._tab("Task and member links")
        ttk.Label(tab, text="Create or remove assignments, skill requirements, and task dependencies.").pack(anchor="w", pady=(0, 12))
        self.links_tree = self._table(tab, ("id", "task", "type", "related"),
            ("Link ID", "Task", "Relationship", "Related record"), (70, 240, 150, 300))
        self._buttons(tab, [("Assign member", self.assign_member, True), ("Add required skill", self.add_task_skill, False),
            ("Add dependency", self.add_dependency, False), ("Remove selected link", self.remove_link, False)])

    def build_history_tab(self):
        tab = self._tab("History records")
        ttk.Label(tab, text="Assignment actions are recorded automatically. Manual audit entries can be added here.",
                  wraplength=800).pack(anchor="w", pady=(0, 12))
        self.history_tree = self._table(tab, ("id", "action", "member", "task", "date"),
            ("ID", "Action", "Member", "Task", "Date"), (65, 110, 170, 260, 180))
        self._buttons(tab, [("Add history record", self.add_history, True)])

    def refresh(self):
        self.data = {"members": retrieve.get_all_members(), "tasks": retrieve.get_all_tasks(),
            "skills": retrieve.get_all_skills(), "statuses": retrieve.get_all_statuses(),
            "dependencies": retrieve.get_all_dependencies(), "history": retrieve.get_all_history()}
        self.by_member = {row["member_id"]: row for row in self.data["members"]}
        self.by_task = {row["task_id"]: row for row in self.data["tasks"]}
        self.by_skill = {row["skill_id"]: row for row in self.data["skills"]}
        self.by_status = {row["status_id"]: row for row in self.data["statuses"]}
        self.refresh_members()
        self.refresh_catalog()
        self.refresh_tasks()
        self.refresh_links()
        self.refresh_history()

    def refresh_members(self):
        self._clear(self.member_tree)
        for row in self.data["members"]:
            self.member_tree.insert("", "end", iid=str(row["member_id"]), values=(row["member_id"], row["name"],
                "Available" if row["available"] else "Unavailable", "Lead" if row["role"] else "Member",
                row["workload"], ", ".join(s["name"] for s in row["skills"]) or "—"))

    def refresh_catalog(self):
        self._clear(self.skill_tree)
        for row in self.data["skills"]:
            self.skill_tree.insert("", "end", iid=str(row["skill_id"]), values=(row["skill_id"], row["name"]))
        self._clear(self.status_tree)
        for row in self.data["statuses"]:
            self.status_tree.insert("", "end", iid=str(row["status_id"]), values=(row["status_id"], row["definition"]))

    def refresh_tasks(self):
        self._clear(self.tasks_tree)
        for row in self.data["tasks"]:
            self.tasks_tree.insert("", "end", iid=str(row["task_id"]), values=(row["task_id"], row["name"],
                row["duration"], row["status"], row["priority"], row["slack"],
                ", ".join(a["name"] for a in row["assignees"]) or "Unassigned",
                ", ".join(s["name"] for s in row["required_skills"]) or "—"))

    def refresh_links(self):
        self._clear(self.links_tree)
        for task in self.data["tasks"]:
            tid = task["task_id"]
            for assignee in task["assignees"]:
                iid = f"assignment:{tid}:{assignee['member_id']}"
                self.links_tree.insert("", "end", iid=iid, values=(iid, task["name"], "Assignment", assignee["name"]))
            for skill in task["required_skills"]:
                iid = f"required:{tid}:{skill['skill_id']}"
                self.links_tree.insert("", "end", iid=iid, values=(iid, task["name"], "Required skill", skill["name"]))
        for dep in self.data["dependencies"]:
            iid = f"dependency:{dep['dependency_id']}"
            self.links_tree.insert("", "end", iid=iid, values=(iid, dep["task_name"], "Dependency", dep["predecessor_name"]))

    def refresh_history(self):
        self._clear(self.history_tree)
        for row in self.data["history"]:
            self.history_tree.insert("", "end", iid=str(row["change_id"]), values=(row["change_id"], row["action"],
                row["assignee_name"] or "Former member", row["task_name"], row["created_at"]))

    def create_member(self):
        fields = [
            {"key": "name", "label": "Member name"},
            {"key": "available", "label": "Availability", "kind": "boolean",
             "options": [("Available", True), ("Unavailable", False)], "default": True},
            {"key": "role", "label": "Role", "kind": "boolean",
             "options": [("Team member", False), ("Team lead / approver", True)], "default": False},
            {"key": "skills", "label": "Skills", "kind": "multi",
             "options": [(s["name"], s["skill_id"]) for s in self.data["skills"]]},
        ]
        def save(data):
            member_id = create.add_member(data["name"], 0, data["available"], data["role"])
            try:
                for skill_id in data["skills"]:
                    create.add_member_skill(member_id, skill_id)
            except Exception:
                delete.delete_member(member_id)
                raise
            followups = triggers.member_became_available(member_id) if data["available"] else []
            return member_id, followups
        self._form("Create team member", fields, save,
            lambda result: messagebox.showinfo("Member created", f"Created member #{result[0]}.", parent=self))

    def create_task(self):
        fields = [
            {"key": "name", "label": "Task name"},
            {"key": "duration", "label": "Duration (days)", "kind": "int", "default": 1},
            {"key": "priority", "label": "Priority (0–5)", "kind": "int", "default": 1},
            {"key": "slack", "label": "Slack (days)", "kind": "int", "default": 1},
            {"key": "status", "label": "Status", "kind": "choice",
             "options": [(s["definition"], s["status_id"]) for s in self.data["statuses"]],
             "default": next((s["status_id"] for s in self.data["statuses"] if s["definition"] == "Pending"), None)},
            {"key": "skills", "label": "Required skills", "kind": "multi",
             "options": [(s["name"], s["skill_id"]) for s in self.data["skills"]]},
            {"key": "dependencies", "label": "Predecessor tasks", "kind": "multi",
             "options": [(f"#{t['task_id']} — {t['name']}", t["task_id"]) for t in self.data["tasks"]]},
            {"key": "assignees", "label": "Initial assignees", "kind": "multi",
             "options": [(m["name"], m["member_id"]) for m in self.data["members"] if m["available"]]},
        ]
        def save(data):
            tid = create.add_task(data["duration"], data["name"], data["priority"], data["slack"], data["status"])
            try:
                for sid in data["skills"]: create.add_required_skill(sid, tid)
                for predecessor in data["dependencies"]: create.add_dependency(predecessor, tid)
                for mid in data["assignees"]: create.assign_task(tid, mid)
            except Exception:
                delete.delete_task(tid)
                raise
            followups = []
            for mid in data["assignees"]:
                followups.extend(triggers.member_became_overloaded(mid))
            decision = triggers.task_created(tid)
            if decision:
                followups.append(decision)
            return tid, followups
        def success(result):
            tid, followups = result
            message = f"Created task #{tid}."
            if followups:
                message += f" {len(followups)} follow-up decision(s) were created."
            messagebox.showinfo("Task created", message, parent=self)
        self._form("Create task", fields, save, success)
    def edit_member(self):
        member_id = self._selected_id(self.member_tree, "member")
        if member_id is None:
            return
        member = self.by_member[member_id]
        fields = [
            {"key": "name", "label": "Member name", "default": member["name"]},
            {"key": "available", "label": "Availability", "kind": "boolean",
             "options": [("Available", True), ("Unavailable", False)], "default": bool(member["available"])},
            {"key": "role", "label": "Role", "kind": "boolean",
             "options": [("Team member", False), ("Team lead / approver", True)], "default": bool(member["role"])},
            {"key": "skills", "label": "Skills", "kind": "multi",
             "options": [(s["name"], s["skill_id"]) for s in self.data["skills"]],
             "selected": [s["skill_id"] for s in member["skills"]]},
        ]
        self._form("Edit member", fields, lambda data: self._save_member(member, data))

    def _save_member(self, old, data):
        member_id = old["member_id"]
        old_skills = {skill["skill_id"] for skill in old["skills"]}
        new_skills = set(data["skills"])
        if data["name"] != old["name"]:
            update.update_member_name(member_id, data["name"])
        if data["role"] != bool(old["role"]):
            update.update_member_role(member_id, data["role"])
        if data["available"] != bool(old["available"]):
            update.update_member_availability(member_id, data["available"])
        for skill_id in sorted(old_skills - new_skills):
            delete.delete_member_skill(member_id, skill_id)
        for skill_id in sorted(new_skills - old_skills):
            create.add_member_skill(member_id, skill_id)

        followups = []
        if data["available"] != bool(old["available"]):
            followups.extend(triggers.member_availability_changed(member_id))
        for skill_id in sorted(old_skills - new_skills):
            followups.extend(triggers.member_skill_removed(member_id, skill_id))
        for skill_id in sorted(new_skills - old_skills):
            followups.extend(triggers.member_skill_added(member_id, skill_id))
        return followups

    def add_member_skill(self):
        member_id = self._selected_id(self.member_tree, "member")
        if member_id is None:
            return
        member = self.by_member[member_id]
        held = {s["skill_id"] for s in member["skills"]}
        options = [(s["name"], s["skill_id"]) for s in self.data["skills"] if s["skill_id"] not in held]
        def save(data):
            added = create.add_member_skill(member_id, data["skill"])
            followups = triggers.member_skill_added(member_id, data["skill"]) if added else []
            return {"added": added, "decisions": followups}
        self._form("Add member skill", [{"key": "skill", "label": "Skill", "kind": "choice", "options": options}], save)

    def remove_member_skill(self):
        member_id = self._selected_id(self.member_tree, "member")
        if member_id is None:
            return
        member = self.by_member[member_id]
        options = [(s["name"], s["skill_id"]) for s in member["skills"]]
        self._form("Remove member skill", [{"key": "skill", "label": "Skill", "kind": "choice", "options": options}],
                   lambda d: self._delete_member_skill(member_id, d["skill"]))

    def _delete_member_skill(self, member_id, skill_id):
        removed = delete.delete_member_skill(member_id, skill_id)
        followups = triggers.member_skill_removed(member_id, skill_id) if removed else []
        return {"removed": removed, "decisions": followups}

    def remove_member(self):
        member_id = self._selected_id(self.member_tree, "member")
        if member_id is None:
            return
        if messagebox.askyesno("Delete member", "Delete this member? Assigned tasks must be reassigned first.", parent=self):
            self._run(lambda: delete.delete_member(member_id))

    def create_skill(self):
        self._form("Create skill", [{"key": "name", "label": "Skill name"}],
                   lambda d: create.add_skill(d["name"]))

    def edit_skill(self):
        skill_id = self._selected_id(self.skill_tree, "skill")
        if skill_id is None:
            return
        self._form("Rename skill", [{"key": "name", "label": "Skill name", "default": self.by_skill[skill_id]["name"]}],
                   lambda d: update.update_skill(skill_id, d["name"]))

    def remove_skill(self):
        skill_id = self._selected_id(self.skill_tree, "skill")
        if skill_id is not None and messagebox.askyesno("Delete skill", "Delete this skill? It may be in use.", parent=self):
            self._run(lambda: delete.delete_skill(skill_id))

    def create_status(self):
        self._form("Create task status", [{"key": "name", "label": "Status name"}],
                   lambda d: create.add_status(d["name"]))

    def edit_status(self):
        status_id = self._selected_id(self.status_tree, "status")
        if status_id is None:
            return
        row = self.by_status[status_id]
        self._form("Rename status", [{"key": "name", "label": "Status name", "default": row["definition"]}],
                   lambda d: update.update_status(status_id, d["name"]))

    def remove_status(self):
        status_id = self._selected_id(self.status_tree, "status")
        if status_id is not None and messagebox.askyesno("Delete status", "Delete this status? It may be in use.", parent=self):
            self._run(lambda: delete.delete_status(status_id))

    def edit_task(self):
        task_id = self._selected_id(self.tasks_tree, "task")
        if task_id is None:
            return
        task = self.by_task[task_id]
        fields = [
            {"key": "name", "label": "Task name", "default": task["name"]},
            {"key": "duration", "label": "Duration (days)", "kind": "int", "default": task["duration"]},
            {"key": "priority", "label": "Priority (0–5)", "kind": "int", "default": task["priority"]},
            {"key": "slack", "label": "Slack (days)", "kind": "int", "default": task["slack"]},
            {"key": "status", "label": "Status", "kind": "choice",
             "options": [(s["definition"], s["status_id"]) for s in self.data["statuses"]],
             "default": task["status_id"]},
            {"key": "required_skills", "label": "Required skills", "kind": "multi",
             "options": [(s["name"], s["skill_id"]) for s in self.data["skills"]],
             "selected": [s["skill_id"] for s in task["required_skills"]]},
        ]
        self._form("Edit task", fields, lambda data: self._save_task(task, data))

    def _save_task(self, old, data):
        task_id = old["task_id"]
        followups = []
        if data["name"] != old["name"]:
            update.update_task_name(task_id, data["name"])
        if data["duration"] != old["duration"]:
            update.update_task_duration(task_id, data["duration"])
            if data["duration"] > old["duration"]:
                followups.extend(triggers.task_duration_increased(task_id, old["duration"], data["duration"]))
        if data["priority"] != old["priority"]:
            update.update_task_priority(task_id, data["priority"])
        if data["slack"] != old["slack"]:
            update.update_task_slack(task_id, data["slack"])
            if data["slack"] <= 0:
                decision = triggers.task_slack_exhausted(task_id)
                if decision:
                    followups.append(decision)
        if data["status"] != old["status_id"]:
            new_status = next(s["definition"] for s in self.data["statuses"] if s["status_id"] == data["status"])
            update.update_task_status(task_id, data["status"])
            followups.extend(triggers.task_status_changed(task_id, old["status"], new_status))
        if set(data["required_skills"]) != {s["skill_id"] for s in old["required_skills"]}:
            update.update_task_required_skills(task_id, data["required_skills"])
            decision = triggers.task_required_skills_changed(task_id)
            if decision:
                followups.append(decision)
        return followups

    def remove_task(self):
        task_id = self._selected_id(self.tasks_tree, "task")
        if task_id is not None and messagebox.askyesno("Delete task", "Delete this task and its related records?", parent=self):
            self._run(lambda: delete.delete_task(task_id))

    def _run(self, operation):
        try:
            result = operation()
            self.refresh()
            self.on_change()
            count = self.on_decisions(result) if self.on_decisions else 0
            if not count:
                messagebox.showinfo("Change saved", "The change was saved.", parent=self)
            return result
        except Exception as exc:
            messagebox.showerror("Unable to complete action", str(exc), parent=self)
            return None

    def assign_member(self):
        fields = [
            {"key": "task", "label": "Task", "kind": "choice",
             "options": [(f"#{t['task_id']} — {t['name']}", t["task_id"]) for t in self.data["tasks"]]},
            {"key": "member", "label": "Member", "kind": "choice",
             "options": [(f"#{m['member_id']} — {m['name']}", m["member_id"]) for m in self.data["members"]]},
        ]
        def save(data):
            change_id = create.assign_task(data["task"], data["member"])
            followups = triggers.member_became_overloaded(data["member"])
            return {"change_id": change_id, "decisions": followups}
        self._form("Assign member to task", fields, save)

    def add_task_skill(self):
        fields = [
            {"key": "task", "label": "Task", "kind": "choice",
             "options": [(f"#{t['task_id']} — {t['name']}", t["task_id"]) for t in self.data["tasks"]]},
            {"key": "skill", "label": "Required skill", "kind": "choice",
             "options": [(s["name"], s["skill_id"]) for s in self.data["skills"]]},
        ]
        def save(data):
            added = create.add_required_skill(data["skill"], data["task"])
            decision = triggers.required_skill_added(data["task"], data["skill"]) if added else None
            return {"added": added, "decisions": [decision] if decision else []}
        self._form("Add task skill requirement", fields, save)

    def add_dependency(self):
        tasks = [(f"#{t['task_id']} — {t['name']}", t["task_id"]) for t in self.data["tasks"]]
        fields = [
            {"key": "predecessor", "label": "Predecessor task", "kind": "choice", "options": tasks},
            {"key": "task", "label": "Task that depends on it", "kind": "choice", "options": tasks},
        ]
        def save(data):
            dependency_id = create.add_dependency(data["predecessor"], data["task"])
            decision = triggers.dependency_changed(data["task"])
            return {"dependency_id": dependency_id, "decisions": [decision] if decision else []}
        self._form("Add task dependency", fields, save)

    def remove_link(self):
        selection = self.links_tree.selection()
        if not selection:
            messagebox.showinfo("Select a relationship", "Select a relationship to remove.", parent=self)
            return
        parts = selection[0].split(":")
        link_type = parts[0]
        if not messagebox.askyesno("Remove relationship", "Remove the selected relationship?", parent=self):
            return
        try:
            followups = []
            if link_type == "assignment":
                _kind, task_text, member_text = parts
                task_id, member_id = int(task_text), int(member_text)
                update.unassign_member(task_id, member_id)
                decision = triggers.task_unassigned(task_id)
                if decision:
                    followups.append(decision)
            elif link_type == "required":
                _kind, task_text, skill_text = parts
                task_id = int(task_text)
                delete.delete_required_skill(int(skill_text), task_id)
                decision = triggers.task_required_skills_changed(task_id)
                if decision:
                    followups.append(decision)
            elif link_type == "dependency":
                dependency_id = int(parts[1])
                dependency = next(d for d in self.data["dependencies"] if d["dependency_id"] == dependency_id)
                delete.delete_dependency(dependency_id)
                decision = triggers.dependency_changed(dependency["task_id"])
                if decision:
                    followups.append(decision)
            self.refresh()
            self.on_change()
            if self.on_decisions:
                self.on_decisions(followups)
            if not followups:
                messagebox.showinfo("Relationship removed", "The relationship was removed.", parent=self)
        except Exception as exc:
            messagebox.showerror("Unable to remove relationship", str(exc), parent=self)

    def add_history(self):
        fields = [
            {"key": "action", "label": "Action", "kind": "choice",
             "options": [("Assigned", "assigned"), ("Unassigned", "unassigned")]},
            {"key": "member", "label": "Team member", "kind": "choice",
             "options": [(f"#{m['member_id']} — {m['name']}", m["member_id"]) for m in self.data["members"]]},
            {"key": "task", "label": "Task", "kind": "choice",
             "options": [(f"#{t['task_id']} — {t['name']}", t["task_id"]) for t in self.data["tasks"]]},
        ]
        self._form("Add history record", fields,
                   lambda d: create.add_history(d["action"], d["member"], d["task"]))





