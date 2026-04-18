"""
AgentX — Message Bus
════════════════════
SQLite-backed inter-agent communication bus.
Agents can send direct messages, broadcast to all, and escalate to the CEO.

Usage:
    from agents.message_bus import BUS
    BUS.send("ATLAS", "MARCUS", "NOTIFY", "DB schema ready for security review")
    BUS.broadcast("ATLAS", "ANNOUNCE", "Phase 1 complete ✅")
    BUS.escalate_to_ceo("MARCUS", "Critical vulnerability found in API auth layer")
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Database path ──────────────────────────────────────────────────────────────
_ROOT    = Path(__file__).parent.parent
_DB_PATH = _ROOT / "ledger" / "messages.db"


# ── Message types ──────────────────────────────────────────────────────────────
class MsgType:
    NOTIFY     = "NOTIFY"       # one-way notification
    QUERY      = "QUERY"        # request for information
    RESPONSE   = "RESPONSE"     # reply to a QUERY
    ANNOUNCE   = "ANNOUNCE"     # broadcast announcement
    ALERT      = "ALERT"        # urgent attention needed
    ESCALATE   = "ESCALATE"     # CEO-level escalation (priority 2)
    MEETING    = "MEETING"      # meeting invitation or transcript
    VOTE       = "VOTE"         # governance vote notification
    TASK       = "TASK"         # task assignment


class MessageBus:
    """
    SQLite-backed message bus for inter-agent communication.

    Schema:
        messages (id, ts, from_ag, to_ag, msg_type, content, thread_id, priority, is_read)

    Priority levels:
        0 — normal
        1 — high (shows in agent notification area)
        2 — CEO escalation (shows in CEO dashboard panel)
    """

    def __init__(self, db_path: Path = _DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT    NOT NULL,
                    from_ag    TEXT    NOT NULL,
                    to_ag      TEXT,              -- NULL = broadcast to all
                    msg_type   TEXT    NOT NULL,
                    content    TEXT    NOT NULL,
                    thread_id  TEXT,              -- groups related messages
                    priority   INTEGER DEFAULT 0, -- 0=normal 1=high 2=ceo
                    is_read    INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_to_ag   ON messages(to_ag)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_from_ag ON messages(from_ag)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priority ON messages(priority)")
            conn.commit()

    # ── Write operations ───────────────────────────────────────────────────────

    def send(
        self,
        from_ag:   str,
        to_ag:     Optional[str],
        msg_type:  str,
        content:   str,
        thread_id: Optional[str] = None,
        priority:  int = 0,
    ) -> int:
        """Send a message from one agent to another (or broadcast if to_ag=None)."""
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            cur = conn.execute(
                "INSERT INTO messages (ts, from_ag, to_ag, msg_type, content, thread_id, priority) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, from_ag, to_ag, msg_type, content, thread_id, priority),
            )
            msg_id = cur.lastrowid
            conn.commit()

        target = to_ag or "ALL"
        prio_tag = " 🔴" if priority == 2 else " 🟡" if priority == 1 else ""
        print(f"\n  📨 MSG  {from_ag} → {target}  [{msg_type}]{prio_tag}  {content[:70]}")
        return msg_id

    def broadcast(self, from_ag: str, msg_type: str, content: str, priority: int = 0) -> int:
        """Broadcast a message to all agents (to_ag = NULL)."""
        return self.send(from_ag, None, msg_type, content, priority=priority)

    def escalate_to_ceo(self, from_ag: str, reason: str, details: str = "") -> int:
        """Send a priority-2 CEO escalation. Appears in the CEO dashboard panel."""
        content = reason if not details else f"{reason}\n\n{details[:300]}"
        return self.send(from_ag, "CEO", MsgType.ESCALATE, content, priority=2)

    # ── Read operations ────────────────────────────────────────────────────────

    def get_recent(self, limit: int = 50, since_id: int = 0) -> list[dict]:
        """Return recent messages, optionally after a specific ID."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM messages WHERE id > ? ORDER BY id DESC LIMIT ?",
                (since_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_for_agent(self, agent_name: str, since_id: int = 0) -> list[dict]:
        """Return messages addressed to this agent (or broadcast) since a given ID."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM messages "
                "WHERE id > ? AND (to_ag = ? OR to_ag IS NULL) "
                "ORDER BY id ASC",
                (since_id, agent_name),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_ceo_escalations(self, limit: int = 20) -> list[dict]:
        """Return all CEO-priority escalation messages."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM messages WHERE priority = 2 ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_thread(self, thread_id: str) -> list[dict]:
        """Return all messages in a conversation thread."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC",
                (thread_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_max_id(self) -> int:
        """Return the highest message ID (for polling)."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            row = conn.execute("SELECT MAX(id) FROM messages").fetchone()
        return row[0] or 0

    def mark_read(self, message_ids: list[int]) -> None:
        """Mark specific messages as read."""
        if not message_ids:
            return
        placeholders = ",".join("?" * len(message_ids))
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.execute(
                f"UPDATE messages SET is_read = 1 WHERE id IN ({placeholders})",
                message_ids,
            )
            conn.commit()

    def get_stats(self) -> dict:
        """Return summary stats for the dashboard."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            total      = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            unread     = conn.execute("SELECT COUNT(*) FROM messages WHERE is_read=0").fetchone()[0]
            escalations = conn.execute("SELECT COUNT(*) FROM messages WHERE priority=2").fetchone()[0]
        return {"total": total, "unread": unread, "escalations": escalations}


# ── Global singleton ───────────────────────────────────────────────────────────
BUS = MessageBus()
