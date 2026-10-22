"""
Database connection and SQLite lifecycle management for AI Dev Team.
Provides thread-safe connections, foreign key enforcement, WAL journal mode, and schema migrations.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional


DEFAULT_DB_PATH = os.environ.get(
    "AI_DEV_TEAM_DB_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "ai_dev_team.db"))
)


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Aktif veritabanı dosya yolunu döndürür."""
    if custom_path:
        return custom_path
    return os.environ.get("AI_DEV_TEAM_DB_PATH", DEFAULT_DB_PATH)


def create_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    SQLite veritabanı bağlantısı oluşturur:
    - sqlite3.Row row_factory (sözlük benzeri erişim)
    - PRAGMA foreign_keys = ON (İlişkisel bütünlük)
    - PRAGMA journal_mode = WAL (Yüksek eşzamanlılık ve dayanıklılık)
    - PRAGMA busy_timeout = 5000 (Kilitlenmeleri önleme)
    """
    path = get_db_path(db_path)
    # Bellek içi olmayan yollarda üst dizini oluştur
    if path != ":memory:":
        parent_dir = os.path.dirname(os.path.abspath(path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(
        path,
        timeout=10.0,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


@contextmanager
def get_db_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """
    İşlem (transaction) güvenli veritabanı bağlam yöneticisi.
    Hata durumunda otomatik rollback, başarıda commit yapar.
    """
    conn = create_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """
    Veritabanı tablolarını ve indekslerini oluşturur (DDL).
    """
    with get_db_connection(db_path) as conn:
        # 1. Görevler tablosu
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                plan_json TEXT,
                scope_json TEXT,
                coder_json TEXT,
                tester_json TEXT,
                reviewer_json TEXT,
                events_json TEXT,
                error TEXT
            );
        """)

        # 2. İş akışı çalıştırma geçmişi tablosu (Workflow Runs)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                run_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                duration_ms REAL,
                error TEXT,
                plan_json TEXT,
                scope_json TEXT,
                coder_json TEXT,
                tester_json TEXT,
                reviewer_json TEXT,
                events_json TEXT,
                agent_metrics_json TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
        """)

        # 3. Performans ve sorgu indeksleri
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_runs_task_id ON workflow_runs(task_id, run_number ASC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_runs_started_at ON workflow_runs(started_at DESC);")

        _ensure_column(conn, "tasks", "retry_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "tasks", "retry_history_json", "TEXT")
        _ensure_column(conn, "workflow_runs", "retry_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "workflow_runs", "retry_history_json", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    """Var olan SQLite tablosuna eksik kolonu ekler."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names = {row["name"] for row in rows}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
