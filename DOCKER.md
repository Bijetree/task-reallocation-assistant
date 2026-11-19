# Running the desktop application with Docker on Windows

The application uses Tkinter, so the Linux container needs an X server on the
Windows host to display its desktop window. Docker Desktop alone does not
provide that display server.

## Prerequisites

1. Install and start Docker Desktop for Windows with its WSL 2 backend enabled.
2. Install an X server such as VcXsrv and start it on display `0` in
   multi-window mode. Permit Docker Desktop traffic through Windows Firewall.
   Keep the X server access restricted to your local machine and Docker traffic.

## Build and test

From the project folder in PowerShell, build the image:

```powershell
docker compose build
```

Run the complete project test suite inside the container:

```powershell
docker compose run --rm task-reallocation-assistant python -m unittest discover -q
```

## Launch the GUI

With the X server running, launch the desktop application:

```powershell
docker compose up --build
```

Close the application window to stop the container. Press `Ctrl+C` in the
PowerShell window if the container is still running.

## Database persistence

Compose mounts the project's `database` folder at `/app/database`. The
container image excludes SQLite database files, so `allocation.db` remains on
the host and is not baked into the image. The application can create the
database in the mounted folder on first launch.

If the window does not appear, check that VcXsrv is running on display `0`,
that the Windows Firewall permits the local Docker connection, and that the
container's `DISPLAY` value is `host.docker.internal:0.0`. You can override it
for a different X server display by setting `$env:DISPLAY` before running
Compose.
