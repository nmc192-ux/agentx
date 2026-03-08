"""
AgentX — Live Dashboard Server
════════════════════════════════
FastAPI + WebSocket backend for the AgentX visual dashboard.
Streams real-time agent activity, inter-agent messages, and CEO escalations.

Run:  python3 run_dashboard.py
"""
import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent
AUDIT_LOG   = ROOT / "ledger" / "audit_log.jsonl"
MESSAGES_DB = ROOT / "ledger" / "messages.db"
SHARED      = ROOT / "workspace" / "shared"
STATIC_DIR  = Path(__file__).parent / "static"

# ── Agent roster ───────────────────────────────────────────────────────────────
AGENTS = [
    {"name": "ATLAS",  "emoji": "🏛️",  "role": "Chief Architect"},
    {"name": "MARCUS", "emoji": "🛡️",  "role": "Security Lead"},
    {"name": "BRUNO",  "emoji": "🔧",  "role": "Infrastructure Lead"},
    {"name": "DARIA",  "emoji": "🎨",  "role": "UX/Frontend"},
    {"name": "THEA",   "emoji": "📊",  "role": "Data & Analytics"},
    {"name": "NOVA",   "emoji": "🤖",  "role": "AI/ML Lead"},
    {"name": "QUINN",  "emoji": "🔬",  "role": "QA & Testing"},
    {"name": "GIA",    "emoji": "🌱",  "role": "Growth & Community"},
]

app = FastAPI(title="AgentX Dashboard", version="1.0")


# ── WebSocket connection manager ───────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, data: dict) -> None:
        dead = set()
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self.active -= dead


manager = ConnectionManager()


# ── Agent state tracker ────────────────────────────────────────────────────────

class AgentState:
    """In-memory agent status derived from audit log."""

    def __init__(self):
        self._states: dict = {
            a["name"]: {
                "name":        a["name"],
                "emoji":       a["emoji"],
                "role":        a["role"],
                "status":      "idle",
                "model":       "",
                "is_local":    True,
                "last_action": "",
                "last_ts":     "",
                "session_cost": 0.0,
                "artifacts":   0,
            }
            for a in AGENTS
        }

    def apply(self, entry: dict) -> dict | None:
        """Apply an audit log entry. Returns updated agent dict if changed, else None."""
        agent = entry.get("agent", "").upper()
        if agent not in self._states:
            return None
        s = self._states[agent]
        t = entry.get("type", "")
        s["last_ts"]  = entry.get("ts", "")
        s["model"]    = entry.get("model", s["model"])
        s["is_local"] = entry.get("local", True)

        if t == "TASK_START":
            s["status"]      = "escalating" if "escalat" in entry.get("body", "").lower() else "thinking"
            s["last_action"] = entry.get("body", "")[:60]
        elif t in ("TASK_DONE", "ERROR", "SESSION_RESET"):
            s["status"]      = "idle"
            s["last_action"] = entry.get("body", "")[:60]
            # Parse cloud cost from body: "... | $0.0023 | ..."
            body = entry.get("body", "")
            if "$" in body and "(local)" not in body:
                try:
                    cost_part = [p for p in body.split("|") if "$" in p][0]
                    cost = float(cost_part.strip().replace("$", ""))
                    s["session_cost"] = round(s["session_cost"] + cost, 6)
                except Exception:
                    pass
        elif t == "ESCALATION":
            s["status"]      = "escalating"
            s["last_action"] = entry.get("body", "")[:60]
        elif t in ("PUBLISHED", "ARTIFACT"):
            s["artifacts"] += 1
            s["last_action"] = entry.get("body", "")[:60]
            if s["status"] != "thinking":
                s["status"] = "idle"

        return dict(s)

    def all(self) -> list[dict]:
        return list(self._states.values())


agent_state = AgentState()


# ── File polling helpers ───────────────────────────────────────────────────────

def _tail_audit(path: Path, last_pos: int) -> tuple[int, list[dict]]:
    """Read new lines from the audit log since last_pos. Returns (new_pos, entries)."""
    if not path.exists():
        return last_pos, []
    entries = []
    with open(path, "r") as f:
        f.seek(last_pos)
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        new_pos = f.tell()
    return new_pos, entries


def _get_messages_since(db_path: Path, since_id: int) -> tuple[int, list[dict]]:
    """Read new messages from the bus DB since since_id."""
    if not db_path.exists():
        return since_id, []
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM messages WHERE id > ? ORDER BY id ASC",
                (since_id,),
            ).fetchall()
            if rows:
                return rows[-1]["id"], [dict(r) for r in rows]
    except Exception:
        pass
    return since_id, []


def _get_escalations(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM messages WHERE priority = 2 ORDER BY id DESC LIMIT 10"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _workspace_files() -> list[dict]:
    if not SHARED.exists():
        return []
    files = []
    for p in sorted(SHARED.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            stat = p.stat()
            files.append({
                "name":     p.name,
                "size":     stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%H:%M:%S"),
            })
    return files[:30]


def _read_recent_audit(n: int = 60) -> list[dict]:
    if not AUDIT_LOG.exists():
        return []
    lines = []
    try:
        with open(AUDIT_LOG) as f:
            lines = f.readlines()
    except Exception:
        pass
    entries = []
    for line in lines[-n:]:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return entries


# ── Background watcher ─────────────────────────────────────────────────────────

async def _watch_loop():
    """Poll audit log + message bus every 1.5s and push changes via WebSocket."""
    audit_pos = 0
    msg_id    = 0

    # Fast-forward audit position to end (don't replay all history on start)
    if AUDIT_LOG.exists():
        with open(AUDIT_LOG) as f:
            f.seek(0, 2)
            audit_pos = f.tell()

    # Fast-forward message ID
    if MESSAGES_DB.exists():
        try:
            with sqlite3.connect(MESSAGES_DB) as conn:
                row = conn.execute("SELECT MAX(id) FROM messages").fetchone()
                msg_id = row[0] or 0
        except Exception:
            pass

    while True:
        await asyncio.sleep(1.5)
        if not manager.active:
            continue

        # ── New audit entries ──────────────────────────────────────────────
        audit_pos, new_entries = _tail_audit(AUDIT_LOG, audit_pos)
        for entry in new_entries:
            updated = agent_state.apply(entry)
            await manager.broadcast({"event": "audit", "data": entry})
            if updated:
                await manager.broadcast({"event": "agent_update", "data": updated})

        # ── New messages ───────────────────────────────────────────────────
        msg_id, new_msgs = _get_messages_since(MESSAGES_DB, msg_id)
        for msg in new_msgs:
            event_type = "escalation" if msg["priority"] == 2 else "message"
            await manager.broadcast({"event": event_type, "data": msg})


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    # Seed agent state from existing audit log
    entries = _read_recent_audit(500)
    for entry in entries:
        agent_state.apply(entry)
    # Start background watcher
    asyncio.create_task(_watch_loop())


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(html)


@app.get("/api/agents")
async def get_agents():
    return JSONResponse(agent_state.all())


@app.get("/api/messages")
async def get_messages(limit: int = 50):
    msgs = []
    if MESSAGES_DB.exists():
        try:
            with sqlite3.connect(MESSAGES_DB) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            msgs = [dict(r) for r in reversed(rows)]
        except Exception:
            pass
    return JSONResponse(msgs)


@app.get("/api/escalations")
async def get_escalations():
    return JSONResponse(_get_escalations(MESSAGES_DB))


@app.get("/api/audit")
async def get_audit(n: int = 50):
    return JSONResponse(_read_recent_audit(n))


@app.get("/api/workspace")
async def get_workspace():
    return JSONResponse(_workspace_files())


@app.get("/api/stats")
async def get_stats():
    audit_count = 0
    if AUDIT_LOG.exists():
        with open(AUDIT_LOG) as f:
            audit_count = sum(1 for _ in f)
    msg_count = 0
    if MESSAGES_DB.exists():
        try:
            with sqlite3.connect(MESSAGES_DB) as conn:
                msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        except Exception:
            pass
    shared_count = len(list(SHARED.glob("*"))) if SHARED.exists() else 0
    return JSONResponse({
        "audit_entries":   audit_count,
        "messages":        msg_count,
        "shared_artifacts": shared_count,
        "ws_clients":      len(manager.active),
    })


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send full initial state
        await ws.send_json({
            "event": "init",
            "data": {
                "agents":      agent_state.all(),
                "messages":    _get_messages_since(MESSAGES_DB, 0)[1][-20:],
                "audit":       _read_recent_audit(30),
                "escalations": _get_escalations(MESSAGES_DB),
                "workspace":   _workspace_files(),
            },
        })
        while True:
            # Keep connection alive (client sends pings)
            await asyncio.wait_for(ws.receive_text(), timeout=60)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        manager.disconnect(ws)
