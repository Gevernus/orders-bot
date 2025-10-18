import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_DB_PATH = os.environ.get("DB_PATH", "/app/data/orders.db")


def _ensure_parent_dir_exists(path: str) -> None:
    parent_dir = os.path.dirname(path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)


@contextmanager
def get_conn(db_path: Optional[str] = None):
    path = db_path or DEFAULT_DB_PATH
    _ensure_parent_dir_exists(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                full_name_en TEXT NOT NULL,
                city TEXT NOT NULL,
                dates TEXT NOT NULL,
                main_link TEXT NOT NULL,
                backup_link TEXT,
                extra_request TEXT,
                promo_code TEXT,
                status TEXT NOT NULL DEFAULT 'В работе',
                assigned_admin_id INTEGER,
                taken_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        # Add columns for backward compatibility if DB was created earlier
        cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
        if "assigned_admin_id" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN assigned_admin_id INTEGER")
        if "taken_at" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN taken_at TEXT")


def insert_order(order: Dict[str, Any], db_path: Optional[str] = None) -> int:
    now = datetime.utcnow().isoformat()
    values = (
        order["user_id"],
        order["platform"],
        order["full_name_en"],
        order["city"],
        order["dates"],
        order.get("main_link", ""),
        order.get("backup_link", ""),
        order.get("extra_request", ""),
        order.get("promo_code", ""),
        order.get("status", "В работе"),
        order.get("assigned_admin_id"),
        order.get("taken_at"),
        now,
        now,
    )

    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO orders (
                user_id, platform, full_name_en, city, dates,
                main_link, backup_link, extra_request, promo_code,
                status, assigned_admin_id, taken_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        return int(cur.lastrowid)


def get_orders(limit: int = 20, offset: int = 0, include_closed: bool = False, db_path: Optional[str] = None) -> List[sqlite3.Row]:
    with get_conn(db_path) as conn:
        base = "SELECT * FROM orders"
        if not include_closed:
            base += " WHERE status != 'Закрыт'"
        base += " ORDER BY id DESC LIMIT ? OFFSET ?"
        cur = conn.execute(base, (limit, offset))
        return list(cur.fetchall())


def update_order_status(order_id: int, status: str, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.utcnow().isoformat(), order_id),
        )


def assign_order_to_admin(order_id: int, admin_id: int, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE orders SET assigned_admin_id = ?, taken_at = ?, updated_at = ? WHERE id = ?",
            (admin_id, datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), order_id),
        )


def get_waiting_orders(limit: int = 20, offset: int = 0, db_path: Optional[str] = None) -> List[sqlite3.Row]:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM orders WHERE assigned_admin_id IS NULL AND status != 'Закрыт' ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return list(cur.fetchall())


def get_orders_by_admin(admin_id: int, limit: int = 20, offset: int = 0, db_path: Optional[str] = None) -> List[sqlite3.Row]:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM orders WHERE assigned_admin_id = ? AND status != 'Закрыт' ORDER BY id DESC LIMIT ? OFFSET ?",
            (admin_id, limit, offset),
        )
        return list(cur.fetchall())


