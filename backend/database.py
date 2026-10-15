import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent / "storm_automation.db"


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS storm_requests (
                alert_id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS change_assessments (
                alert_id TEXT NOT NULL,
                sys_id TEXT NOT NULL,
                change_number TEXT,
                assessment_json TEXT NOT NULL,
                work_note_status TEXT NOT NULL DEFAULT 'pending',
                exception_status TEXT NOT NULL DEFAULT 'not_required',
                decision_note_status TEXT NOT NULL DEFAULT 'not_required',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (alert_id, sys_id),
                FOREIGN KEY (alert_id)
                    REFERENCES storm_requests(alert_id)
            )
        """)


def save_storm(alert):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO storm_requests
                (alert_id, data_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(alert_id) DO UPDATE SET
                data_json = excluded.data_json
        """, (
            alert["id"],
            json.dumps(alert),
            alert["created_at"],
        ))


def get_storm(alert_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT data_json FROM storm_requests
            WHERE alert_id = ?
        """, (alert_id,)).fetchone()

    return json.loads(row["data_json"]) if row else None


def list_storms():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT data_json FROM storm_requests
            ORDER BY created_at DESC
        """).fetchall()

    return [json.loads(row["data_json"]) for row in rows]


def get_assessment(alert_id, sys_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM change_assessments
            WHERE alert_id = ? AND sys_id = ?
        """, (alert_id, sys_id)).fetchone()

    if not row:
        return None

    item = dict(row)
    item["assessment"] = json.loads(item.pop("assessment_json"))
    return item


def save_assessment(alert_id, change, assessment):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO change_assessments (
                alert_id, sys_id, change_number, assessment_json
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(alert_id, sys_id) DO UPDATE SET
                change_number = excluded.change_number,
                assessment_json = excluded.assessment_json,
                updated_at = CURRENT_TIMESTAMP
        """, (
            alert_id,
            change["sys_id"],
            change.get("number"),
            json.dumps(assessment),
        ))


def update_work_note_status(alert_id, sys_id, status):
    with get_connection() as conn:
        conn.execute("""
            UPDATE change_assessments
            SET work_note_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE alert_id = ? AND sys_id = ?
        """, (status, alert_id, sys_id))


def update_exception_decision(
    alert_id, sys_id, decision, note_status
):
    with get_connection() as conn:
        conn.execute("""
            UPDATE change_assessments
            SET exception_status = ?,
                decision_note_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE alert_id = ? AND sys_id = ?
        """, (decision, note_status, alert_id, sys_id))


def list_assessments(alert_id):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM change_assessments
            WHERE alert_id = ?
        """, (alert_id,)).fetchall()

    result = []

    for row in rows:
        item = dict(row)
        item["risk_assessment"] = json.loads(
            item.pop("assessment_json")
        )
        result.append(item)

    return result

def list_exception_assessments(alert_id=None):
    with get_connection() as conn:
        if alert_id:
            rows = conn.execute(
                """
                SELECT * FROM change_assessments
                WHERE alert_id = ?
                ORDER BY updated_at DESC
                """,
                (alert_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM change_assessments
                ORDER BY updated_at DESC
                """
            ).fetchall()

    result = []

    for row in rows:
        item = dict(row)
        item["risk_assessment"] = json.loads(
            item.pop("assessment_json")
        )
        result.append(item)

    return result


def set_exception_pending(alert_id, sys_id):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE change_assessments
            SET exception_status = 'pending',
                updated_at = CURRENT_TIMESTAMP
            WHERE alert_id = ? AND sys_id = ?
            """,
            (alert_id, sys_id),
        )


def get_exception(alert_id, sys_id):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM change_assessments
            WHERE alert_id = ? AND sys_id = ?
            """,
            (alert_id, sys_id),
        ).fetchone()

    if not row:
        return None

    item = dict(row)
    item["risk_assessment"] = json.loads(
        item.pop("assessment_json")
    )
    return item


def complete_exception_decision(
    alert_id, sys_id, decision, note_status="updated"
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE change_assessments
            SET exception_status = ?,
                decision_note_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE alert_id = ?
              AND sys_id = ?
              AND exception_status = 'pending'
            """,
            (decision, note_status, alert_id, sys_id),
        )

        return cursor.rowcount == 1