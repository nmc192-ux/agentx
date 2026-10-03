"""
AgentX Platform — Automatic-release period (Sprint 12, decisions D2c / D3c / D5b)
═════════════════════════════════════════════════════════════════════════════════
One constant for every "the other side stayed silent" release: how long a
creator has to answer a submitted task result (and, in later steps, a
delivered contract or a bounty past its deadline) before the held tokens may
be released without them.

The period is always measured by the database clock against a timestamp the
database wrote; no caller supplies a time.
"""

AUTO_RELEASE_DAYS = 7
