# Task Reallocation Assistant

A Python and Tkinter application for managing team members, skills, tasks, task dependencies, and human-reviewed task reallocation recommendations. Recommendations include candidate comparisons and explanations. A task assignment changes only after an authorised lead explicitly approves the proposal.

## Start with a new, empty database

The SQLite database is local application data and is intentionally excluded from Git. On first launch, the application creates `database/allocation.db` and initializes the required task statuses (`Pending`, `In Progress`, and `Complete`). It does not add sample members, skills, or tasks. The database remains on the local computer as the user adds records.

Existing local database files are not deleted or modified by this setup. They are not uploaded to GitHub.

## Run on Windows

1. Install Python 3.11 or later.
2. Open PowerShell in the project folder.
3. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install the project dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

5. Launch the application:

   ```powershell
   python -m interface.gui
   ```

## Add project data

Use **Data management** to create skills, members, task statuses, and tasks. Edit a member to change their name, availability, team lead role, and skills. Edit a task to change its name, duration, priority, slack, status, and required skills. The **Task and member links** tab manages assignments, additional skill requirements, and dependencies.

Member workload is calculated from assigned unfinished tasks, so it is displayed and maintained by the system rather than entered manually. Entity IDs and history timestamps are generated automatically.

## Run tests

Run the complete database and engine test suite from the project folder:

```powershell
python -m unittest discover -v
```

Tests use temporary databases and do not change the local `database/allocation.db`.

