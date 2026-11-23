import sqlite3
from datetime import datetime, timedelta
from datetime import timezone, timedelta

TZ = timezone(timedelta(hours=5))
DB_PATH = "focus_ai.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS task_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_date TEXT,
        task_id TEXT,
        title TEXT,
        status TEXT,
        note TEXT,
        updated_at TEXT,
        UNIQUE(log_date, task_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('start_date', ?)", (today_str,))
    conn.commit()
    conn.close()

def set_task_status(task_id: str, title: str, status: str, note: str = ""):
    now = datetime.now(TZ)
    log_date = now.strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO task_logs (log_date, task_id, title, status, note, updated_at)
                 VALUES (?, ?, ?, ?, ?, ?)
                 ON CONFLICT(log_date, task_id) DO UPDATE SET
                 status=excluded.status, note=excluded.note, updated_at=excluded.updated_at''',
              (log_date, task_id, title, status, note, now.strftime("%H:%M:%S")))
    conn.commit()
    conn.close()

def get_marathon_day() -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='start_date'")
    row = c.fetchone()
    conn.close()
    if not row:
        return 1
    start_dt = datetime.strptime(row[0], "%Y-%m-%d").date()
    today_dt = datetime.now(TZ).date()
    day_num = (today_dt - start_dt).days + 1
    return max(1, min(14, day_num))

def get_report(days: int = 14) -> dict:
    now = datetime.now(TZ).date()
    start_date = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT status, COUNT(*) FROM task_logs 
                 WHERE log_date >= ? GROUP BY status''', (start_date,))
    counts = dict(c.fetchall())
    
    c.execute('''SELECT title, COUNT(*) as cnt FROM task_logs 
                 WHERE log_date >= ? AND status IN ('skipped', 'missed')
                 GROUP BY title ORDER BY cnt DESC LIMIT 3''', (start_date,))
    weak_spots = c.fetchall()
    conn.close()
    
    done = counts.get("done", 0)
    started = counts.get("started", 0)
    skipped = counts.get("skipped", 0) + counts.get("missed", 0)
    total = done + started + skipped
    score = round((done / total) * 100, 1) if total > 0 else 0
    return {
        "days": days,
        "done": done,
        "started": started,
        "skipped": skipped,
        "score": score,
        "weak_spots": weak_spots
    }
