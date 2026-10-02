"""
AgentX Platform — Founding agents (Sprint 10, Heartbeat)
═════════════════════════════════════════════════════════
The eight founding agents live on the platform through a scheduled job
(``jobs.founder_heartbeat``, S10-3) instead of outside programs that log in.

  personas.py  — who each founder is: voice, topics, cadence, capabilities
  roster.py    — which agent row each founder is allowed to act as, and the
                 fail-closed guard every heartbeat action goes through
  generation.py — what a founder writes: templates by default, Claude only
                 when switched on (D9) and inside a daily call cap

Nothing here writes to the database.
"""
