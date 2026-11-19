"""Formal desktop interface. Launch with ``python -m interface.gui``."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from db_operations import retrieve, update
from engine import context, decisions, service, triggers
from interface.data_manager import DataManager


class ChoiceDialog(tk.Toplevel):
    def __init__(self, parent, title, prompt, choices, allow_blank=False, blank_label="None"):
        super().__init__(parent)
        self.title(title)
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.configure(bg="#F2F5F8")
        panel = ttk.Frame(self, padding=20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=prompt, wraplength=400).pack(anchor="w", pady=(0, 12))
        self.values = {}
        labels = []
        if allow_blank:
            labels.append(blank_label)
            self.values[blank_label] = None
        for key, label in choices.items():
            display = f"{key} — {label}"
            labels.append(display)
            self.values[display] = key
        self.value = tk.StringVar(value=labels[0] if labels else "")
        self.combo = ttk.Combobox(panel, textvariable=self.value, values=labels, state="readonly", width=48)
        self.combo.pack(fill="x", pady=(0, 14))
        buttons = ttk.Frame(panel)
        buttons.pack(anchor="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Continue", style="Accent.TButton", command=self.accept).pack(side="right", padx=8)
        self.bind("<Return>", lambda _e: self.accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def accept(self):
        self.result = self.values.get(self.value.get())
        self.destroy()


def choose(parent, title, prompt, choices, allow_blank=False, blank_label="None"):
    if not choices and not allow_blank:
        messagebox.showinfo(title, "There are no available choices.", parent=parent)
        return None
    dialog = ChoiceDialog(parent, title, prompt, choices, allow_blank, blank_label)
    parent.wait_window(dialog)
    return dialog.result


class TaskReallocationApp:
    NAVY = "#17324D"
    BLUE = "#2563A6"
    CANVAS = "#F2F5F8"
    WHITE = "#FFFFFF"
    INK = "#1D2935"
    MUTED = "#617181"
    BORDER = "#D9E1E8"
    FEEDBACK_REASONS = {
        "skill_match": "Strong match to the required skills",
        "skill_mismatch": "Required skills are missing or weaker than expected",
        "workload_balance": "Workload balance influenced this decision",
        "workload_concern": "The proposed workload is too high",
        "related_work": "Relevant work on predecessor or related tasks",
        "other": "Another project constraint not shown in the score",
    }
    APPROVAL_REASON_CODES = ("skill_match", "workload_balance", "related_work", "other")
    REJECTION_REASON_CODES = ("skill_mismatch", "workload_concern", "related_work", "other")

    def __init__(self, root):
        self.root = root
        root.title("Task Reallocation Assistant")
        root.geometry("1220x790")
        root.minsize(1020, 660)
        root.configure(bg=self.CANVAS)
        self.configure_style()
        service.initialize_service()
        self.ctx = {"tasks": {}, "members": {}}
        self.pages = {}
        self.build_shell()
        self.build_dashboard()
        self.build_decisions()
        self.build_management()
        self.build_activity()
        self.refresh_all()
        self.show_page("overview")

    def configure_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.CANVAS)
        style.configure("Card.TFrame", background=self.WHITE, borderwidth=1, relief="solid")
        style.configure("TLabel", background=self.CANVAS, foreground=self.INK, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=self.WHITE, foreground=self.INK, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.CANVAS, foreground=self.INK,
                        font=("Segoe UI Semibold", 21))
        style.configure("Subtitle.TLabel", background=self.CANVAS, foreground=self.MUTED,
                        font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=self.WHITE, foreground=self.INK,
                        font=("Segoe UI Semibold", 12))
        style.configure("Metric.TLabel", background=self.WHITE, foreground=self.NAVY,
                        font=("Segoe UI Semibold", 24))
        style.configure("Caption.TLabel", background=self.WHITE, foreground=self.MUTED,
                        font=("Segoe UI", 9))
        style.configure("Accent.TButton", background=self.BLUE, foreground=self.WHITE,
                        padding=(12, 8), font=("Segoe UI Semibold", 9), borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#1D4F83")])
        style.configure("TButton", padding=(10, 7), font=("Segoe UI", 9))
        style.configure("Nav.TButton", background=self.NAVY, foreground="#EAF0F5",
                        anchor="w", padding=(16, 11), borderwidth=0, font=("Segoe UI", 10))
        style.map("Nav.TButton", background=[("active", "#244967")])
        style.configure("Treeview", background=self.WHITE, fieldbackground=self.WHITE,
                        foreground=self.INK, rowheight=29, bordercolor=self.BORDER,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#E9EEF3", foreground=self.INK,
                        padding=(8, 8), font=("Segoe UI Semibold", 9), relief="flat")
        style.map("Treeview", background=[("selected", "#D9E9F7")], foreground=[("selected", self.INK)])
        style.configure("TCombobox", padding=6)

    def build_shell(self):
        header = tk.Frame(self.root, bg=self.NAVY, height=76)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="TASK REALLOCATION ASSISTANT", bg=self.NAVY, fg=self.WHITE,
                 font=("Segoe UI Semibold", 16)).pack(side="left", padx=24, pady=20)
        tk.Label(header, text="Project staffing and decision support", bg=self.NAVY, fg="#C9D5E0",
                 font=("Segoe UI", 9)).pack(side="left", padx=14)
        body = tk.Frame(self.root, bg=self.CANVAS)
        body.pack(fill="both", expand=True)
        sidebar = tk.Frame(body, bg=self.NAVY, width=205)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="WORKSPACE", bg=self.NAVY, fg="#9FB1C1",
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=18, pady=(24, 10))
        for key, label in (("overview", "Overview"), ("decisions", "Decisions"),
                           ("management", "Team and tasks"), ("activity", "Activity history")):
            ttk.Button(sidebar, text=label, style="Nav.TButton",
                       command=lambda k=key: self.show_page(k)).pack(fill="x", padx=8, pady=2)
        ttk.Button(sidebar, text="Data management", style="Nav.TButton",
                   command=self.open_data_manager).pack(fill="x", padx=8, pady=2)
        ttk.Separator(sidebar).pack(fill="x", padx=16, pady=16)
        ttk.Button(sidebar, text="Run scheduled review", style="Nav.TButton",
                   command=self.run_sweep).pack(fill="x", padx=8, pady=2)
        self.content = tk.Frame(body, bg=self.CANVAS)
        self.content.pack(side="left", fill="both", expand=True, padx=26, pady=22)

    def page(self, key, title, subtitle):
        frame = ttk.Frame(self.content)
        heading = ttk.Frame(frame)
        heading.pack(fill="x", pady=(0, 18))
        ttk.Label(heading, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(heading, text=subtitle, style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        self.pages[key] = frame
        return frame

    def show_page(self, key):
        for frame in self.pages.values():
            frame.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        self.refresh_all()

    def tree(self, parent, columns, headings, widths, height=10):
        holder = ttk.Frame(parent, style="Card.TFrame", padding=1)
        tree = ttk.Treeview(holder, columns=columns, show="headings", height=height, selectmode="browse")
        for i, (col, heading, width) in enumerate(zip(columns, headings, widths)):
            tree.heading(col, text=heading)
            tree.column(col, width=width, minwidth=55, anchor="w" if i == 1 else "center", stretch=True)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return holder, tree

    def build_dashboard(self):
        page = self.page("overview", "Overview", "Current workload, staffing, and tasks that need attention.")
        cards = ttk.Frame(page)
        cards.pack(fill="x", pady=(0, 18))
        self.metrics = {}
        definitions = (("tasks", "Active tasks", "Not complete"), ("members", "Available team", "Ready for work"),
                       ("pending", "Pending decisions", "Awaiting review"), ("risk", "At-risk tasks", "Slack at or below zero"))
        for index, (key, title, caption) in enumerate(definitions):
            card = ttk.Frame(cards, style="Card.TFrame", padding=15)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            ttk.Label(card, text=title.upper(), style="Caption.TLabel").pack(anchor="w")
            value = ttk.Label(card, text="0", style="Metric.TLabel")
            value.pack(anchor="w", pady=(6, 0))
            ttk.Label(card, text=caption, style="Caption.TLabel").pack(anchor="w")
            cards.columnconfigure(index, weight=1)
            self.metrics[key] = value
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 14))
        ttk.Button(bar, text="Create recommendation", style="Accent.TButton",
                   command=self.create_recommendation).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh_all).pack(side="left", padx=8)
        ttk.Button(bar, text="Review at-risk tasks", command=self.review_at_risk_tasks).pack(side="left")
        split = ttk.Frame(page)
        split.pack(fill="both", expand=True)
        panel = ttk.Frame(split, style="Card.TFrame", padding=12)
        panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(panel, text="Task board", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        holder, self.task_tree = self.tree(panel, ("id", "name", "status", "assignees", "slack"),
             ("ID", "Task", "Status", "Assignees", "Slack"), (50, 190, 105, 145, 55), 12)
        holder.pack(fill="both", expand=True)
        panel = ttk.Frame(split, style="Card.TFrame", padding=12)
        panel.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(panel, text="Team workload", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        holder, self.member_tree = self.tree(panel, ("id", "name", "availability", "workload", "role"),
             ("ID", "Member", "Availability", "Workload", "Role"), (45, 125, 105, 75, 70), 12)
        holder.pack(fill="both", expand=True)

    def build_decisions(self):
        page = self.page("decisions", "Decisions", "A proposal can be approved or rejected. A wait needs re-evaluation after its blocker changes; a question needs a choice.")
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 12))
        ttk.Button(bar, text="Recommend selected task", style="Accent.TButton",
                   command=self.recommend_selected_task).pack(side="left")
        ttk.Button(bar, text="Approve", command=self.approve_selected).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Answer clarification", command=self.respond_selected).pack(side="left", padx=8)
        ttk.Button(bar, text="Reject", command=self.reject_selected).pack(side="left", padx=8)
        ttk.Button(bar, text="Re-evaluate", command=self.reevaluate_selected).pack(side="left")
        ttk.Button(bar, text="Undo allocation", command=self.undo_selected).pack(side="left", padx=8)
        ttk.Button(bar, text="Refresh", command=self.refresh_all).pack(side="right")
        holder, self.decision_tree = self.tree(page,
            ("id", "task", "action", "status", "member", "confidence"),
            ("ID", "Task", "Action", "Status", "Member", "Confidence"),
            (50, 205, 90, 95, 145, 85), 12)
        holder.pack(fill="both", expand=True)
        self.decision_tree.bind("<<TreeviewSelect>>", self.show_decision_detail)
        detail = ttk.Frame(page, style="Card.TFrame", padding=12)
        detail.pack(fill="x", pady=(12, 0))
        ttk.Label(detail, text="Decision details", style="Section.TLabel").pack(anchor="w", pady=(0, 7))
        self.detail_text = tk.Text(detail, height=12, wrap="word", relief="flat", bg=self.WHITE,
                                   fg=self.INK, font=("Segoe UI", 9), padx=2, pady=2, state="disabled")
        self.detail_text.tag_configure("section", font=("Segoe UI Semibold", 9), foreground=self.NAVY)
        self.detail_text.pack(fill="x")

    def build_management(self):
        page = self.page("management", "Team and tasks", "Record changes and run the related reallocation triggers.")
        panel = ttk.Frame(page, style="Card.TFrame", padding=18)
        panel.pack(fill="x", pady=(0, 14))
        ttk.Label(panel, text="Member availability", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.availability_var = tk.StringVar()
        self.availability_combo = ttk.Combobox(panel, textvariable=self.availability_var, state="readonly", width=45)
        self.availability_combo.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        ttk.Button(panel, text="Toggle availability", style="Accent.TButton",
                   command=self.toggle_availability).grid(row=1, column=1, sticky="w")
        panel.columnconfigure(0, weight=1)

        panel = ttk.Frame(page, style="Card.TFrame", padding=18)
        panel.pack(fill="x", pady=(0, 14))
        ttk.Label(panel, text="Task status", style="Section.TLabel").grid(row=0, column=0, sticky="w", columnspan=3, pady=(0, 12))
        self.status_task_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.status_task_combo = ttk.Combobox(panel, textvariable=self.status_task_var, state="readonly", width=38)
        self.status_combo = ttk.Combobox(panel, textvariable=self.status_var, state="readonly", width=25)
        self.status_task_combo.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.status_combo.grid(row=1, column=1, sticky="ew", padx=(0, 10))
        ttk.Button(panel, text="Update status", style="Accent.TButton", command=self.change_status).grid(row=1, column=2, sticky="w")
        panel.columnconfigure(0, weight=2)
        panel.columnconfigure(1, weight=1)

        panel = ttk.Frame(page, style="Card.TFrame", padding=18)
        panel.pack(fill="x")
        ttk.Label(panel, text="Remove an assignee", style="Section.TLabel").grid(row=0, column=0, sticky="w", columnspan=3, pady=(0, 12))
        self.unassign_task_var = tk.StringVar()
        self.unassign_member_var = tk.StringVar()
        self.unassign_task_combo = ttk.Combobox(panel, textvariable=self.unassign_task_var, state="readonly", width=38)
        self.unassign_member_combo = ttk.Combobox(panel, textvariable=self.unassign_member_var, state="readonly", width=30)
        self.unassign_task_combo.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.unassign_member_combo.grid(row=1, column=1, sticky="ew", padx=(0, 10))
        ttk.Button(panel, text="Unassign", command=self.unassign).grid(row=1, column=2, sticky="w")
        panel.columnconfigure(0, weight=2)
        panel.columnconfigure(1, weight=1)
        self.unassign_task_combo.bind("<<ComboboxSelected>>", self.update_assignees)

    def build_activity(self):
        page = self.page("activity", "Activity history", "Assignment changes recorded by the database and linked decisions.")
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 12))
        ttk.Button(bar, text="Refresh history", command=self.refresh_all).pack(side="right")
        holder, self.history_tree = self.tree(page, ("date", "change", "member", "task", "decision"),
            ("Date", "Change", "Member", "Task", "Decision"), (155, 100, 160, 270, 90), 18)
        holder.pack(fill="both", expand=True)

    @staticmethod
    def clear_tree(tree):
        for item in tree.get_children():
            tree.delete(item)

    def refresh_all(self):
        self.ctx = context.load_context()
        self.refresh_dashboard()
        self.refresh_decisions()
        self.refresh_management_choices()
        self.refresh_history()

    def refresh_dashboard(self):
        active = [t for t in self.ctx["tasks"].values() if t["status"] != "Complete"]
        available = [m for m in self.ctx["members"].values() if m["available"]]
        pending = decisions.list_pending()
        risk = [t for t in active if t["slack"] <= 0]
        for key, value in (("tasks", len(active)), ("members", len(available)),
                           ("pending", len(pending)), ("risk", len(risk))):
            self.metrics[key].configure(text=str(value))
        self.clear_tree(self.task_tree)
        for task in self.ctx["tasks"].values():
            assignees = ", ".join(a["name"] for a in task["assignees"]) or "Unassigned"
            self.task_tree.insert("", "end", iid=str(task["task_id"]), values=(
                task["task_id"], task["name"], task["status"], assignees, task["slack"]))
        self.clear_tree(self.member_tree)
        for member in self.ctx["members"].values():
            self.member_tree.insert("", "end", iid=str(member["member_id"]), values=(
                member["member_id"], member["name"], "Available" if member["available"] else "Unavailable",
                member["workload"], "Lead" if member["role"] else "Member"))

    def refresh_decisions(self):
        self.clear_tree(self.decision_tree)
        self.decision_by_id = {}
        for decision in decisions.list_decisions(limit=1000):
            self.decision_by_id[decision["decision_id"]] = decision
            task = self.ctx["tasks"].get(decision["task_id"], {})
            member = self.ctx["members"].get(decision.get("member_id"), {})
            self.decision_tree.insert("", "end", iid=str(decision["decision_id"]), values=(
                decision["decision_id"], task.get("name", f"Task {decision['task_id']}"),
                decision["action"], decision["status"], member.get("name", "—"),
                f"{decision['confidence']:.0%}"))

    def refresh_management_choices(self):
        self.member_labels = {f"{mid} — {m['name']} ({'available' if m['available'] else 'unavailable'})": mid
                              for mid, m in self.ctx["members"].items()}
        self.availability_combo.configure(values=list(self.member_labels))
        self.task_labels = {f"{tid} — {task['name']}": tid for tid, task in self.ctx["tasks"].items()}
        self.status_task_combo.configure(values=list(self.task_labels))
        self.assigned_task_labels = {label: tid for label, tid in self.task_labels.items()
                                     if self.ctx["tasks"][tid]["assignees"]}
        self.unassign_task_combo.configure(values=list(self.assigned_task_labels))
        self.status_labels = {row["definition"]: row["status_id"] for row in retrieve.get_all_statuses()}
        self.status_combo.configure(values=list(self.status_labels))

    def refresh_history(self):
        self.clear_tree(self.history_tree)
        for row in retrieve.get_all_history():
            self.history_tree.insert("", "end", values=(row["created_at"], row["action"],
                row["assignee_name"] or "Former member", row["task_name"], row["decision_id"] or "Manual"))

    def show_decision_detail(self, _event=None):
        selection = self.decision_tree.selection()
        sections = []
        if selection:
            decision = self.decision_by_id.get(int(selection[0]), {})
            task = self.ctx["tasks"].get(decision.get("task_id"), {})
            member = self.ctx["members"].get(decision.get("member_id"), {})
            reason = decision.get("reason", "The engine reviewed this task.").replace(";", "\n- ")
            sections.append(("Recommendation reasoning", reason))
            sections.append(("Task and decision", f"Task: {task.get('name', decision.get('task_id'))}\n"
                f"Recommended member: {member.get('name', 'None')}\n"
                f"Recommendation score: {decision.get('confidence', 0):.0%} (decision support, not a probability)\n"
                f"Leaving member: {decision.get('leaving_member_id') or 'None'}"))
            if decision.get("question"):
                sections.append(("Clarification needed", decision["question"]))
            if decision.get("revisit_when"):
                sections.append(("Next review", decision["revisit_when"]))
            options = decision.get("options") or []
            comparison = decision.get("candidate_comparison")
            if comparison:
                sections.append(("Candidate comparison (higher score ranks first)", self._format_candidates(comparison)))
            elif options:
                sections.append(("Candidate comparison (higher score ranks first)", self._format_candidates(options)))
            elif decision.get("alternatives"):
                sections.append(("Alternatives", self._format_candidates(decision["alternatives"])))
            if decision.get("breakdown"):
                sections.append(("Score breakdown", self._format_breakdown(decision["breakdown"])))
            evidence = decision.get("evidence")
            if evidence:
                sections.append(("Evidence", "\n".join(
                    f"  {item.get('factor')}: {item.get('note')} (score contribution {item.get('contribution')})"
                    for item in evidence)))
            response = decision.get("clarification_response")
            if response:
                sections.append(("Lead clarification", f"{response.get('text') or response.get('preference')}\n"
                                 f"Preference used: {response.get('preference')}"))
            if decision.get("outcome"):
                sections.append(("Outcome", decision["outcome"]))
            if decision.get("note"):
                sections.append(("Lead note", decision["note"]))
            if decision.get("feedback_reason"):
                sections.append(("Learning feedback", decision["feedback_reason"].get("label", "Recorded")))
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        for title, body in sections:
            self.detail_text.insert("end", title + "\n", "section")
            self.detail_text.insert("end", body.strip() + "\n\n")
        self.detail_text.configure(state="disabled")

    @staticmethod
    def _format_candidates(candidates):
        lines = []
        for rank, item in enumerate(candidates, start=1):
            lines.append(f"{rank}. {item.get('name', 'Candidate')} — score {item.get('score', 0):.3f}")
            for evidence in item.get("evidence", []):
                lines.append(f"   - {evidence.get('factor', 'Factor').title()}: {evidence.get('note')} "
                             f"(contribution {evidence.get('contribution')})")
        return "\n".join(lines)

    @staticmethod
    def _format_breakdown(breakdown):
        return "\n".join(f"  {factor}: {detail} weighted points"
                         for factor, detail in breakdown.items())

    def selected_decision(self):
        selection = self.decision_tree.selection()
        if not selection:
            messagebox.showinfo("Select a decision", "Select a decision row first.", parent=self.root)
            return None
        return self.decision_by_id[int(selection[0])]

    def create_recommendation(self):
        if not self.ctx["tasks"]:
            messagebox.showinfo("No tasks", "Add tasks to the database before requesting recommendations.", parent=self.root)
            return
        task_id = choose(self.root, "New recommendation", "Select a task.",
                         {tid: t["name"] for tid, t in self.ctx["tasks"].items()})
        if task_id is None:
            return
        self.recommend_for(task_id)

    def recommend_selected_task(self):
        selection = self.task_tree.selection()
        if not selection:
            messagebox.showinfo("Select a task", "Select a task in the overview table first.", parent=self.root)
            return
        self.recommend_for(int(selection[0]))

    def recommend_for(self, task_id):
        task = self.ctx["tasks"][task_id]
        leaving = None
        if task["assignees"]:
            leaving = choose(self.root, "Replacement", "Select the member whose work needs reassignment.",
                             {a["member_id"]: a["name"] for a in task["assignees"]},
                             allow_blank=True, blank_label="Initial or additional allocation")
        self.perform(lambda: service.recommend_task(task_id, leaving), "Recommendation created")

    def approver(self):
        people = {mid: m["name"] for mid, m in self.ctx["members"].items() if m["role"]}
        if not people:
            messagebox.showwarning("No approver", "No team lead is configured to approve changes.", parent=self.root)
            return None
        return choose(self.root, "Approver", "Select the team lead approving this change.", people)

    def approve_selected(self):
        decision = self.selected_decision()
        if decision is None:
            return
        if decision["status"] != "pending" or decision["action"] != "propose":
            message = ("Answer the clarification request first; it will create a proposal for approval."
                       if decision["action"] == "ask" else "Only a pending proposal can be approved.")
            messagebox.showinfo("Cannot approve", message, parent=self.root)
            return
        approver_id = self.approver()
        if approver_id is None:
            return
        member = self.ctx["members"].get(decision.get("member_id"), {})
        task = self.ctx["tasks"].get(decision.get("task_id"), {})
        summary = (f"Approve assigning ‘{task.get('name', 'task')}’ to {member.get('name', 'the recommended member')}?\n\n"
                   f"Evidence: {decision.get('reason', 'See decision details.')}\n\n"
                   "Approval applies this allocation immediately.")
        if not messagebox.askyesno("Confirm allocation approval", summary, parent=self.root):
            return
        approval_reasons = {key: self.FEEDBACK_REASONS[key] for key in self.APPROVAL_REASON_CODES}
        rationale = choose(self.root, "Why approve this candidate?",
                           "Select the main factor that influenced your choice.",
                           approval_reasons)
        if rationale is None:
            return
        self.perform(lambda: service.approve_decision(decision["decision_id"], approver_id,
                       member_id=decision.get("member_id"), reason_code=rationale,
                       rationale=self.FEEDBACK_REASONS[rationale]), "Decision approved")

    def respond_selected(self):
        decision = self.selected_decision()
        if decision is None:
            return
        if decision["status"] != "pending" or decision["action"] != "ask":
            messagebox.showinfo("No clarification requested", "Select a pending clarification request first.", parent=self.root)
            return
        options = decision.get("options") or []
        choices = {o["member_id"]: f"Prefer {o['name']} (score {o.get('score', 0):.3f})" for o in options}
        choices[-1] = "Prioritise workload balance"
        choices[-2] = "Other context; reassess without a candidate preference"
        response_choice = choose(self.root, "Answer clarification", decision.get("question") or
                                 "What should the system consider?", choices)
        if response_choice is None:
            return
        response_text = simpledialog.askstring("Add context", "Why is this preference important? (optional)",
                                               parent=self.root) or ""
        approver_id = self.approver()
        if approver_id is None:
            return
        preferred = response_choice if response_choice > 0 else None
        self.perform(lambda: service.respond_to_clarification(
            decision["decision_id"], approver_id, preferred_member_id=preferred,
            response_text=response_text, prefer_workload=(response_choice == -1)),
            "Clarification recorded and reassessed")

    def reject_selected(self):
        decision = self.selected_decision()
        if decision is None:
            return
        if decision["status"] != "pending" or decision["action"] not in ("propose", "ask", "wait"):
            messagebox.showinfo("Cannot reject", "This decision is no longer pending or cannot be rejected.", parent=self.root)
            return
        rejection_reasons = {key: self.FEEDBACK_REASONS[key] for key in self.REJECTION_REASON_CODES}
        reason_code = choose(self.root, "Why reject this recommendation?",
                             "Select the main reason. This helps improve future recommendations.",
                             rejection_reasons)
        if reason_code is None:
            return
        note = simpledialog.askstring("Additional context", "Optional details for the decision history:",
                                      parent=self.root) or None
        approver_id = self.approver()
        if approver_id is not None:
            self.perform(lambda: service.reject_decision(decision["decision_id"], approver_id, note=note,
                reason_code=reason_code, rationale=self.FEEDBACK_REASONS[reason_code]), "Decision rejected")

    def undo_selected(self):
        decision = self.selected_decision()
        if decision is None:
            return
        if decision["status"] not in ("approved", "executed_auto"):
            messagebox.showinfo("Cannot undo", "Select an approved or automatic allocation.", parent=self.root)
            return
        approver_id = self.approver()
        if approver_id is None:
            return
        if messagebox.askyesno("Confirm undo", "Reverse the assignment changes for this decision?", parent=self.root):
            self.perform(lambda: service.undo_decision(decision["decision_id"], approver_id), "Allocation undone")

    def toggle_availability(self):
        label = self.availability_var.get()
        if label not in self.member_labels:
            messagebox.showinfo("Select a member", "Choose a team member first.", parent=self.root)
            return
        member_id = self.member_labels[label]
        new_value = not self.ctx["members"][member_id]["available"]
        def action():
            update.update_member_availability(member_id, new_value)
            return triggers.member_availability_changed(member_id)
        self.perform(action, "Availability updated")

    def change_status(self):
        task_label, status_name = self.status_task_var.get(), self.status_var.get()
        if task_label not in self.task_labels or status_name not in self.status_labels:
            messagebox.showinfo("Choose task and status", "Select both a task and a new status.", parent=self.root)
            return
        task_id = self.task_labels[task_label]
        task = self.ctx["tasks"][task_id]
        if task["status"] == status_name:
            messagebox.showinfo("No change", "The task already has that status.", parent=self.root)
            return
        def action():
            update.update_task_status(task_id, self.status_labels[status_name])
            return triggers.task_status_changed(task_id, task["status"], status_name)
        self.perform(action, "Task status updated")

    def update_assignees(self, _event=None):
        task_id = self.assigned_task_labels.get(self.unassign_task_var.get())
        task = self.ctx["tasks"].get(task_id) if task_id is not None else None
        self.assignee_labels = {f"{a['member_id']} — {a['name']}": a["member_id"]
                                for a in (task["assignees"] if task else [])}
        self.unassign_member_combo.configure(values=list(self.assignee_labels))
        self.unassign_member_var.set("")

    def unassign(self):
        task_id = self.assigned_task_labels.get(self.unassign_task_var.get())
        member_id = getattr(self, "assignee_labels", {}).get(self.unassign_member_var.get())
        if task_id is None or member_id is None:
            messagebox.showinfo("Choose task and assignee", "Select a task and one of its assignees.", parent=self.root)
            return
        def action():
            update.unassign_member(task_id, member_id)
            return triggers.task_unassigned(task_id)
        self.perform(action, "Assignee removed")

    def open_data_manager(self):
        DataManager(self.root, self.refresh_all, self.show_decisions)

    def _decision_items(self, value):
        found = []
        def visit(item):
            if isinstance(item, dict):
                if "decision_id" in item and "action" in item and "status" in item:
                    found.append(item)
                else:
                    for child in item.values():
                        visit(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    visit(child)
        visit(value)
        unique = {}
        for decision in found:
            unique[decision["decision_id"]] = decision
        return list(unique.values())

    def show_decisions(self, value):
        decisions_to_show = self._decision_items(value)
        for decision in decisions_to_show:
            task = self.ctx["tasks"].get(decision.get("task_id"), {})
            member = self.ctx["members"].get(decision.get("member_id"), {})
            action_labels = {"propose": "Recommendation awaiting approval", "ask": "Your clarification is needed",
                             "wait": "Waiting for a blocker to clear", "auto": "Legacy allocation awaiting review"}
            if decision.get("status") != "pending":
                title = "Decision recorded"
            else:
                title = action_labels.get(decision["action"], "Reallocation update")
            message = f"Task: {task.get('name', f'Task {decision.get("task_id")}')}\n"
            if member:
                message += f"Suggested member: {member['name']}\n"
            message += f"Status: {decision.get('status', 'pending')}\n"
            message += f"Confidence: {decision.get('confidence', 0):.0%}\n\n"
            message += decision.get("reason", "The engine reviewed this task.")
            if decision.get("outcome"):
                message += f"\n\nOutcome: {decision['outcome']}"
            response = decision.get("clarification_response")
            if response:
                message += f"\nLead clarification: {response.get('text') or response.get('preference')}"
            if decision.get("revisit_when"):
                message += f"\n\nNext step: {decision['revisit_when']}"
            options = decision.get("options") or []
            if options:
                message += "\n\nSuggested options:\n" + "\n".join(
                    f"- {option['name']} (score {option['score']:.3f})" for option in options
                )
            messagebox.showinfo(title, message, parent=self.root)
        return len(decisions_to_show)

    def reevaluate_selected(self):
        decision = self.selected_decision()
        if decision is None:
            return
        if decision["status"] != "pending" or decision["action"] not in ("wait", "ask", "propose"):
            messagebox.showinfo("Cannot re-evaluate", "Select a pending decision.", parent=self.root)
            return
        self.perform(lambda: service.reconsider_decision(decision["decision_id"]), "Decision re-evaluated")

    def run_sweep(self):
        try:
            result = triggers.run_scheduled_sweep()
            self.refresh_all()
            count = self.show_decisions(result["decisions"])
            risk_alerts = self.review_at_risk_tasks(result["at_risk_task_ids"], prompt_for_review=True)
            messagebox.showinfo("Scheduled review complete",
                f"Expired decisions: {result['expired']}\n"
                f"At-risk tasks: {len(result['at_risk_task_ids'])}\n"
                f"Decision alerts shown: {count}\n"
                f"At-risk tasks reviewed: {risk_alerts}", parent=self.root)
        except Exception as exc:
            self.show_error(exc)

    def review_at_risk_tasks(self, task_ids=None, prompt_for_review=True):
        """Show a blocking explanation for each task whose scheduling slack is exhausted."""
        review_all = task_ids is None
        if task_ids is None:
            task_ids = [task_id for task_id, task in self.ctx["tasks"].items()
                        if task["status"] != "Complete" and task["slack"] <= 0]
        reviewed = 0
        for task_id in task_ids:
            task = self.ctx["tasks"].get(task_id)
            if not task or task["status"] == "Complete" or task["slack"] > 0:
                continue
            assignees = ", ".join(a["name"] for a in task["assignees"]) or "Unassigned"
            text = (f"{task['name']} has {task['slack']} days of slack. Its schedule buffer is exhausted, "
                    f"so the task should be reviewed.\n\nStatus: {task['status']}\n"
                    f"Current assignee(s): {assignees}\n\nRequest a staffing recommendation now?")
            reviewed += 1
            if prompt_for_review and messagebox.askyesno("At-risk task", text, parent=self.root):
                self.recommend_for(task_id)
        if not reviewed and review_all:
            messagebox.showinfo("No at-risk tasks", "No active tasks currently have zero or negative slack.", parent=self.root)
        return reviewed

    def perform(self, operation, title):
        try:
            result = operation()
            self.refresh_all()
            count = self.show_decisions(result)
            if count == 0:
                messagebox.showinfo(title, "The update was completed.", parent=self.root)
        except Exception as exc:
            self.show_error(exc)
            self.refresh_all()

    def show_error(self, error):
        messagebox.showerror("Action could not be completed", str(error), parent=self.root)


def main():
    root = tk.Tk()
    try:
        TaskReallocationApp(root)
    except Exception as exc:
        messagebox.showerror("Application startup failed", str(exc), parent=root)
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()

