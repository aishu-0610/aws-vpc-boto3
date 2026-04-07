import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "focusgate.db")

conn = sqlite3.connect(DB_PATH)

conn.execute("""
CREATE TABLE IF NOT EXISTS dns_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    domain TEXT,
    blocked INTEGER,
    category TEXT
)
""")

conn.commit()
conn.close()

print("Database initialized successfully.")
