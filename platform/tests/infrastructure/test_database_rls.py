"""
Tests: Row-Level Security enforcement
Sprint 1 — QUINN Gap 1.3 / MARCUS P1 Gap 3

These tests verify PostgreSQL RLS policies using a real test database.
Run with:  pytest tests/infrastructure/test_database_rls.py -v --db

Prerequisites:
  docker compose up -d postgres
  export POSTGRES_HOST=localhost
  export POSTGRES_PASSWORD=<from secrets/db_password.txt>
"""
import asyncio
import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration   # skip unless --db flag is set


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def db_pool():
    """Module-scoped DB pool for integration tests."""
    from src.database import init_pool, close_pool, get_pool
    await init_pool()
    yield get_pool()
    await close_pool()


@pytest_asyncio.fixture
async def two_agents(db_pool):
    """Create two test agents; clean up after each test."""
    from src.database import get_db
    async with get_db() as conn:
        await conn.execute("""
            INSERT INTO agents (agent_did, display_name, agent_type, wallet_address)
            VALUES
              ('did:agentx:alice-test-001', 'ALICE-TEST', 'AUTONOMOUS', '0x' || repeat('a', 40)),
              ('did:agentx:bob-test-001',   'BOB-TEST',   'AUTONOMOUS', '0x' || repeat('b', 40))
            ON CONFLICT (agent_did) DO NOTHING
        """)
        alice_id = await conn.fetchval("SELECT id FROM agents WHERE agent_did = 'did:agentx:alice-test-001'")
        bob_id   = await conn.fetchval("SELECT id FROM agents WHERE agent_did = 'did:agentx:bob-test-001'")
        await conn.execute("""
            INSERT INTO token_balances (agent_id, token_type, balance)
            VALUES ($1, 'WORK', 500.00), ($2, 'WORK', 300.00)
            ON CONFLICT (agent_id, token_type) DO NOTHING
        """, alice_id, bob_id)

    yield {"alice_did": "did:agentx:alice-test-001", "alice_id": alice_id,
           "bob_did": "did:agentx:bob-test-001",     "bob_id": bob_id}

    async with get_db() as conn:
        await conn.execute("DELETE FROM token_balances WHERE agent_id IN ($1, $2)", alice_id, bob_id)
        await conn.execute("DELETE FROM agents WHERE id IN ($1, $2)", alice_id, bob_id)


class TestAgentRLS:
    """Agents table RLS: public read, own-only write."""

    @pytest.mark.asyncio
    async def test_agent_can_read_all_agents(self, two_agents):
        """All agents are visible to any authenticated agent (public directory)."""
        from src.database import get_db_for_agent
        async with get_db_for_agent(two_agents["alice_did"]) as conn:
            rows = await conn.fetch(
                "SELECT agent_did FROM agents WHERE agent_did IN ($1, $2)",
                two_agents["alice_did"], two_agents["bob_did"]
            )
        assert len(rows) == 2, "Alice should see both agents"

    @pytest.mark.asyncio
    async def test_agent_can_update_own_record(self, two_agents):
        """Agent can update their own metadata."""
        from src.database import get_db_for_agent
        async with get_db_for_agent(two_agents["alice_did"]) as conn:
            result = await conn.execute(
                "UPDATE agents SET metadata = '{\"test\": true}'::jsonb WHERE agent_did = $1",
                two_agents["alice_did"]
            )
        assert "UPDATE 1" in result

    @pytest.mark.asyncio
    async def test_agent_cannot_update_other_agent(self, two_agents):
        """
        MARCUS P1 Gap 3: RLS must block agents updating each other's records.
        When Alice tries to UPDATE Bob's agent, 0 rows should be affected.
        """
        from src.database import get_db_for_agent
        async with get_db_for_agent(two_agents["alice_did"]) as conn:
            result = await conn.execute(
                "UPDATE agents SET metadata = '{\"hacked\": true}'::jsonb WHERE agent_did = $1",
                two_agents["bob_did"]
            )
        assert "UPDATE 0" in result, \
            f"RLS should block Alice updating Bob — got: {result}"

        # Verify Bob's record is unchanged
        from src.database import get_db
        async with get_db() as conn:
            meta = await conn.fetchval(
                "SELECT metadata FROM agents WHERE agent_did = $1",
                two_agents["bob_did"]
            )
        assert meta.get("hacked") is None, "Bob's metadata should not be modified"


class TestTokenBalanceRLS:
    """Token balances: each agent sees only their own."""

    @pytest.mark.asyncio
    async def test_agent_sees_own_balance(self, two_agents):
        """Agent can query their own token balance."""
        from src.database import get_db_for_agent
        async with get_db_for_agent(two_agents["alice_did"]) as conn:
            rows = await conn.fetch(
                "SELECT balance FROM token_balances WHERE agent_id = $1 AND token_type = 'WORK'",
                two_agents["alice_id"]
            )
        assert len(rows) == 1
        assert float(rows[0]["balance"]) == pytest.approx(500.00)

    @pytest.mark.asyncio
    async def test_agent_cannot_see_other_agent_balance(self, two_agents):
        """
        MARCUS P1 Gap 3: Agent must not see another agent's token balance.
        Critical — balance is sensitive financial data.
        """
        from src.database import get_db_for_agent
        async with get_db_for_agent(two_agents["alice_did"]) as conn:
            rows = await conn.fetch(
                "SELECT balance FROM token_balances WHERE agent_id = $1 AND token_type = 'WORK'",
                two_agents["bob_id"]
            )
        assert len(rows) == 0, \
            "RLS should prevent Alice from seeing Bob's balance — returned rows unexpectedly"


class TestAuditLogRLS:
    """Audit log: append-only, agents see only their own entries."""

    @pytest.mark.asyncio
    async def test_agent_can_insert_audit_entry(self, two_agents):
        """Agents can write audit entries (required for transparency)."""
        from src.database import get_db_for_agent
        async with get_db_for_agent(two_agents["alice_did"]) as conn:
            await conn.execute("""
                INSERT INTO audit_logs (entry_type, agent_did, body)
                VALUES ('TASK_START', $1, 'RLS test audit entry')
            """, two_agents["alice_did"])
        # No exception = insert succeeded

    @pytest.mark.asyncio
    async def test_agent_cannot_delete_audit_entries(self, two_agents):
        """
        Audit log must be immutable — no DELETE policy exists.
        MARCUS: 'audit log is append-only'.
        """
        from src.database import get_db_for_agent
        async with get_db_for_agent(two_agents["alice_did"]) as conn:
            result = await conn.execute(
                "DELETE FROM audit_logs WHERE agent_did = $1",
                two_agents["alice_did"]
            )
        assert "DELETE 0" in result, \
            "RLS should block DELETE on audit_logs — append-only table"

    @pytest.mark.asyncio
    async def test_agent_only_sees_own_audit_entries(self, two_agents):
        """Agent cannot read other agents' audit log entries."""
        from src.database import get_db_for_agent
        # Seed a Bob audit entry via system (bypasses RLS)
        from src.database import get_db
        async with get_db() as conn:
            await conn.execute("""
                INSERT INTO audit_logs (entry_type, agent_did, body)
                VALUES ('TASK_START', $1, 'Bob private audit entry')
            """, two_agents["bob_did"])

        # Alice queries — should NOT see Bob's entry
        async with get_db_for_agent(two_agents["alice_did"]) as conn:
            rows = await conn.fetch(
                "SELECT body FROM audit_logs WHERE agent_did = $1",
                two_agents["bob_did"]
            )
        assert len(rows) == 0, "Alice should not see Bob's audit log entries"
