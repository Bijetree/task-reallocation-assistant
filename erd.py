from pathlib import Path
from eralchemy2 import render_er
from db import DB_PATH

OUTPUT = DB_PATH.parent / "erd.png"  # also supports .pdf, .svg, .dot, .md

if not DB_PATH.exists():
    raise SystemExit(f"Database not found at {DB_PATH}. Run the init/seed script first.")

# as_posix() keeps the URL valid on Windows (C:/...) as well as Mac/Linux
render_er(f"sqlite:///{DB_PATH.as_posix()}", str(OUTPUT))
print(f"ERD written to {OUTPUT}")