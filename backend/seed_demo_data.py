import sqlite3
import os
import random
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "focusgate.db")

def create_tables(conn):

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

def seed_dns_queries(conn):

    domains = [
        ("youtube.com","entertainment",1),
        ("instagram.com","social",1),
        ("reddit.com","social",1),
        ("twitter.com","social",1),
        ("netflix.com","entertainment",1),
        ("github.com","productive",0),
        ("stackoverflow.com","productive",0),
        ("openai.com","productive",0),
        ("wikipedia.org","productive",0),
        ("geeksforgeeks.org","productive",0),
    ]

    now = datetime.now()
    rows = []

    for i in range(500):

        domain,cat,blocked = random.choice(domains)

        ts = now - timedelta(minutes=random.randint(0,1440))

        rows.append((ts.isoformat(),domain,blocked,cat))

    conn.executemany(
        "INSERT INTO dns_queries (ts,domain,blocked,category) VALUES (?,?,?,?)",
        rows
    )

    conn.commit()

def main():

    print("Adding demo DNS traffic...")

    conn = sqlite3.connect(DB_PATH)

    create_tables(conn)
    seed_dns_queries(conn)

    conn.close()

    print("Demo data inserted successfully!")

if __name__ == "__main__":
    main()