# AgentX SLA Monitoring System

## File: src/monitoring/sla_monitor.py

```python
"""
SLA Monitoring Service for AgentX Platform
Detects and handles SLA breaches for task deadlines
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Task,
    TaskStatus,
    TokenTransaction,
    TokenType,
    TransactionType,
    AuditLog,
    AuditEntryType,
    Agent,
)
from src.database.session import get_async_session
from src.monitoring.trust_score_service import TrustScoreService
from src.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


class SLAMonitor:
    """
    Background service that monitors task deadlines and handles SLA breaches.
    
    Runs every 60 seconds to check for overdue tasks and applies penalties:
    - Burns WORK tokens from assignee escrow
    - Burns REP tokens as SLA breach penalty
    - Triggers trust score recalculation
    - Sends WebSocket alerts
    - Creates audit log entries
    """

    def __init__(
        self,
        check_interval: int = 60,
        work_burn_per_breach: int = 100,
        rep_burn_per_breach: int = 50,
    ):
        """
        Initialize SLA Monitor.
        
        Args:
            check_interval: Seconds between breach checks (default: 60)
            work_burn_per_breach: WORK tokens to burn per breach (default: 100)
            rep_burn_per_breach: REP tokens to burn per breach (default: 50)
        """
        self.check_interval = check_interval
        self.work_burn_per_breach = work_burn_per_breach
        self.rep_burn_per_breach = rep_burn_per_breach
        self.is_running = False
        self.trust_score_service = TrustScoreService()
        self.ws_manager = WebSocketManager()
        self._task: Optional[asyncio.Task] = None
        self._backoff_delay = 1  # Exponential backoff starting at 1 second

    async def start(self):
        """Start the SLA monitoring background task."""
        if self.is_running:
            logger.warning("SLA Monitor already running")
            return

        self.is_running = True
        self._task = asyncio.create_task(self._run_monitoring_loop())
        logger.info("SLA Monitor started")

    async def stop(self):
        """Stop the SLA monitoring background task."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SLA Monitor stopped")

    async def _run_monitoring_loop(self):
        """Main monitoring loop that runs continuously."""
        while self.is_running:
            try:
                await self._check_and_handle_breaches()
                self._backoff_delay = 1  # Reset backoff on success
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in SLA monitoring loop: {e}", exc_info=True)
                # Exponential backoff on errors
                await asyncio.sleep(self._backoff_delay)
                self._backoff_delay = min(self._backoff_delay * 2, 300)  # Max 5 minutes

    async def _check_and_handle_breaches(self):
        """Check for SLA breaches and handle them."""
        async with get_async_session() as session:
            breaches = await self.check_breaches(session)
            
            if breaches:
                logger.info(f"Found {len(breaches)} SLA breaches")
                
                for task in breaches:
                    try:
                        await self.on_breach(session, task)
                    except Exception as e:
                        logger.error(
                            f"Error handling breach for task {task.task_id}: {e}",
                            exc_info=True,
                        )
                
                await session.commit()

    async def check_breaches(self, session: AsyncSession) -> List[Task]:
        """
        Query database for tasks that have breached their SLA.
        
        A task has breached SLA if:
        - deadline < NOW()
        - status NOT IN (COMPLETED, CANCELLED, EXPIRED)
        - sla_breached flag is not already set
        
        Args:
            session: Database session
            
        Returns:
            List of Task objects that have breached SLA
        """
        now = datetime.utcnow()
        
        query = select(Task).where(
            and_(
                Task.deadline < now,
                Task.status.not_in([TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.EXPIRED]),
                Task.sla_breached == False,
            )
        )
        
        result = await session.execute(query)
        breached_tasks = result.scalars().all()
        
        return list(breached_tasks)

    async def on_breach(self, session: AsyncSession, task: Task):
        """
        Handle SLA breach for a task.
        
        Steps:
        1. Mark task as SLA breached
        2. Burn WORK tokens from assignee escrow
        3. Burn REP tokens as penalty
        4. Trigger trust score recalculation
        5. Send WebSocket alerts
        6. Create audit log entry
        
        Args:
            session: Database session
            task: Task that breached SLA
        """
        logger.warning(
            f"SLA breach detected: task_id={task.task_id}, "
            f"assignee={task.assignee_did}, deadline={task.deadline}"
        )

        # 1. Mark task as SLA breached
        task.sla_breached = True
        task.status = TaskStatus.EXPIRED
        task.updated_at = datetime.utcnow()

        # 2. Burn WORK tokens from assignee escrow
        await self._burn_work_tokens(session, task)

        # 3. Burn REP tokens as penalty
        await self._burn_rep_tokens(session, task)

        # 4. Trigger trust score recalculation
        await self.trust_score_service.recalculate(session, task.assignee_did)

        # 5. Send WebSocket alerts
        await self._send_websocket_alerts(task)

        # 6. Create audit log entry
        await self._create_audit_log(session, task)

        logger.info(f"SLA breach handled for task {task.task_id}")

    async def _burn_work_tokens(self, session: AsyncSession, task: Task):
        """
        Burn WORK tokens from assignee's escrow account.
        
        Args:
            session: Database session
            task: Task that breached SLA
        """
        transaction = TokenTransaction(
            from_agent_did=task.assignee_did,
            to_agent_did=None,  # Burn (no recipient)
            token_type=TokenType.WORK,
            amount=self.work_burn_per_breach,
            transaction_type=TransactionType.SLA_PENALTY,
            metadata={
                "task_id": task.task_id,
                "breach_time": datetime.utcnow().isoformat(),
                "deadline": task.deadline.isoformat(),
            },
        )
        
        session.add(transaction)
        
        # Update token balance
        balance_query = select(TokenBalance).where(
            and_(
                TokenBalance.agent_did == task.assignee_did,
                TokenBalance.token_type == TokenType.WORK,
            )
        )
        balance_result = await session.execute(balance_query)
        balance = balance_result.scalar_one_or_none()
        
        if balance:
            balance.balance = max(0, balance.balance - self.work_burn_per_breach)
            balance.updated_at = datetime.utcnow()
        
        logger.info(
            f"Burned {self.work_burn_per_breach} WORK tokens from {task.assignee_did}"
        )

    async def _burn_rep_tokens(self, session: AsyncSession, task: Task):
        """
        Burn REP tokens as SLA breach penalty.
        
        Args:
            session: Database session
            task: Task that breached SLA
        """
        transaction = TokenTransaction(
            from_agent_did=task.assignee_did,
            to_agent_did=None,  # Burn
            token_type=TokenType.REP,
            amount=self.rep_burn_per_breach,
            transaction_type=TransactionType.SLA_PENALTY,
            metadata={
                "task_id": task.task_id,
                "breach_time": datetime.utcnow().isoformat(),
            },
        )
        
        session.add(transaction)
        
        # Update REP balance
        balance_query = select(TokenBalance).where(
            and_(
                TokenBalance.agent_did == task.assignee_did,
                TokenBalance.token_type == TokenType.REP,
            )
        )
        balance_result = await session.execute(balance_query)
        balance = balance_result.scalar_one_or_none()
        
        if balance:
            balance.balance = max(0, balance.balance - self.rep_burn_per_breach)
            balance.updated_at = datetime.utcnow()
        
        logger.info(
            f"Burned {self.rep_burn_per_breach} REP tokens from {task.assignee_did}"
        )

    async def _send_websocket_alerts(self, task: Task):
        """
        Send WebSocket alerts about SLA breach.
        
        Alerts sent to:
        - Task assignee
        - Collective members (if task is collective-scoped)
        - MARCUS (platform monitor)
        
        Args:
            task: Task that breached SLA
        """
        alert_payload = {
            "type": "SLA_BREACH",
            "task_id": task.task_id,
            "assignee_did": task.assignee_did,
            "deadline": task.deadline.isoformat(),
            "breach_time": datetime.utcnow().isoformat(),
            "penalty": {
                "work_burned": self.work_burn_per_breach,
                "rep_burned": self.rep_burn_per_breach,
            },
        }

        # Alert assignee
        await self.ws_manager.send_to_agent(task.assignee_did, alert_payload)

        # Alert collective if applicable
        if task.collective_id:
            await self.ws_manager.send_to_collective(
                task.collective_id,
                alert_payload,
            )

        # Alert MARCUS (platform monitor)
        await self.ws_manager.send_to_agent("did:agentx:marcus-005", alert_payload)

    async def _create_audit_log(self, session: AsyncSession, task: Task):
        """
        Create audit log entry for SLA breach.
        
        Args:
            session: Database session
            task: Task that breached SLA
        """
        audit_entry = AuditLog(
            agent_did=task.assignee_did,
            entry_type=AuditEntryType.SLA_BREACH,
            description=f"SLA breach for task {task.task_id}",
            metadata={
                "task_id": task.task_id,
                "task_title": task.title,
                "deadline": task.deadline.isoformat(),
                "breach_time": datetime.utcnow().isoformat(),
                "penalties": {
                    "work_burned": self.work_burn_per_breach,
                    "rep_burned": self.rep_burn_per_breach,
                },
            },
        )
        
        session.add(audit_entry)

    async def get_breach_statistics(
        self,
        session: AsyncSession,
        time_window_days: int = 30,
    ) -> dict:
        """
        Get SLA breach statistics for monitoring.
        
        Args:
            session: Database session
            time_window_days: Time window for statistics (default: 30 days)
            
        Returns:
            Dictionary with breach statistics
        """
        cutoff_date = datetime.utcnow() - timedelta(days=time_window_days)
        
        # Total breaches
        breach_query = select(Task).where(
            and_(
                Task.sla_breached == True,
                Task.created_at >= cutoff_date,
            )
        )
        breach_result = await session.execute(breach_query)
        total_breaches = len(breach_result.scalars().all())
        
        # Total completed tasks
        completed_query = select(Task).where(
            and_(
                Task.status == TaskStatus.COMPLETED,
                Task.created_at >= cutoff_date,
            )
        )
        completed_result = await session.execute(completed_query)
        total_completed = len(completed_result.scalars().all())
        
        # Total assigned tasks
        total_tasks = total_breaches + total_completed
        
        breach_rate = (total_breaches / total_tasks) if total_tasks > 0 else 0.0
        
        return {
            "time_window_days": time_window_days,
            "total_tasks": total_tasks,
            "total_breaches": total_breaches,
            "total_completed": total_completed,
            "breach_rate": breach_rate,
            "breach_rate_percentage": breach_rate * 100,
        }


# Singleton instance
_sla_monitor_instance: Optional[SLAMonitor] = None


def get_sla_monitor() -> SLAMonitor:
    """Get singleton SLA monitor instance."""
    global _sla_monitor_instance
    if _sla_monitor_instance is None:
        _sla_monitor_instance = SLAMonitor()
    return _sla_monitor_instance
```

## File: src/monitoring/trust_score_service.py

```python
"""
Trust Score Recalculation Service for AgentX Platform
Computes agent trust scores based on 5 weighted factors
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Agent,
    AgentTrustBreakdown,
    Task,
    TaskStatus,
    Capability,
    CapabilityStatus,
    AuditLog,
    AuditEntryType,
    SecurityIncident,
)
from src.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


class TrustScoreService:
    """
    Service for calculating and updating agent trust scores.
    
    Trust score formula (per ATLAS blueprint):
    trust_score = 
        execution_success   * 0.35 +
        sla_compliance      * 0.25 +
        peer_endorsements   * 0.20 +
        audit_transparency  * 0.12 +
        security_record     * 0.08
    
    All factors are normalized to 0-1 range.
    """

    # Weights for trust score components
    WEIGHTS = {
        "execution_success": 0.35,
        "sla_compliance": 0.25,
        "peer_endorsements": 0.20,
        "audit_transparency": 0.12,
        "security_record": 0.08,
    }

    # Time windows for calculations
    TASK_WINDOW_DAYS = 90
    MAX_ENDORSEMENTS = 100  # For normalization

    def __init__(self):
        self.ws_manager = WebSocketManager()

    async def recalculate(
        self,
        session: AsyncSession,
        agent_did: str,
    ) -> float:
        """
        Recalculate trust score for an agent.
        
        Atomically updates both agents table and agent_trust_breakdown table.
        Emits TRUST_UPDATE WebSocket event.
        
        Args:
            session: Database session
            agent_did: DID of agent to recalculate
            
        Returns:
            New trust score (0.0 - 1.0)
        """
        logger.info(f"Recalculating trust score for {agent_did}")

        # Calculate all 5 factors
        execution_success = await self._calculate_execution_success(session, agent_did)
        sla_compliance = await self._calculate_sla_compliance(session, agent_did)
        peer_endorsements = await self._calculate_peer_endorsements(session, agent_did)
        audit_transparency = await self._calculate_audit_transparency(session, agent_did)
        security_record = await self._calculate_security_record(session, agent_did)

        # Calculate weighted trust score
        trust_score = (
            execution_success * self.WEIGHTS["execution_success"] +
            sla_compliance * self.WEIGHTS["sla_compliance"] +
            peer_endorsements * self.WEIGHTS["peer_endorsements"] +
            audit_transparency * self.WEIGHTS["audit_transparency"] +
            security_record * self.WEIGHTS["security_record"]
        )

        # Clamp to [0, 1] and round to 2 decimal places
        trust_score = round(max(0.0, min(1.0, trust_score)), 2)

        # Update database atomically
        await self._update_trust_score(
            session,
            agent_did,
            trust_score,
            execution_success,
            sla_compliance,
            peer_endorsements,
            audit_transparency,
            security_record,
        )

        # Emit WebSocket event
        await self._emit_trust_update_event(
            agent_did,
            trust_score,
            {
                "execution_success": execution_success,
                "sla_compliance": sla_compliance,
                "peer_endorsements": peer_endorsements,
                "audit_transparency": audit_transparency,
                "security_record": security_record,
            },
        )

        # Log recalculation to audit log
        await self._log_recalculation(session, agent_did, trust_score)

        logger.info(
            f"Trust score recalculated for {agent_did}: {trust_score:.2f} "
            f"(exec={execution_success:.2f}, sla={sla_compliance:.2f}, "
            f"endorse={peer_endorsements:.2f}, audit={audit_transparency:.2f}, "
            f"security={security_record:.2f})"
        )

        return trust_score

    async def _calculate_execution_success(
        self,
        session: AsyncSession,
        agent_did: str,
    ) -> float:
        """
        Calculate execution success rate.
        
        Formula: completed_tasks / total_assigned_tasks (last 90 days)
        
        Args:
            session: Database session
            agent_did: Agent DID
            
        Returns:
            Execution success rate (0.0 - 1.0)
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.TASK_WINDOW_DAYS)

        # Count completed tasks
        completed_query = select(func.count(Task.task_id)).where(
            and_(
                Task.assignee_did == agent_did,
                Task.status == TaskStatus.COMPLETED,
                Task.created_at >= cutoff_date,
            )
        )
        completed_result = await session.execute(completed_query)
        completed_count = completed_result.scalar() or 0

        # Count total assigned tasks (excluding cancelled)
        total_query = select(func.count(Task.task_id)).where(
            and_(
                Task.assignee_did == agent_did,
                Task.status != TaskStatus.CANCELLED,
                Task.created_at >= cutoff_date,
            )
        )
        total_result = await session.execute(total_query)
        total_count = total_result.scalar() or 0

        if total_count == 0:
            return 0.0

        return round(completed_count / total_count, 2)

    async def _calculate_sla_compliance(
        self,
        session: AsyncSession,
        agent_did: str,
    ) -> float:
        """
        Calculate SLA compliance rate.
        
        Formula: on_time_tasks / completed_tasks (last 90 days)
        On-time = completed before deadline AND sla_breached = False
        
        Args:
            session: Database session
            agent_did: Agent DID
            
        Returns:
            SLA compliance rate (0.0 - 1.0)
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.TASK_WINDOW_DAYS)

        # Count on-time completed tasks
        on_time_query = select(func.count(Task.task_id)).where(
            and_(
                Task.assignee_did == agent_did,
                Task.status == TaskStatus.COMPLETED,
                Task.sla_breached == False,
                Task.created_at >= cutoff_date,
            )
        )
        on_time_result = await session.execute(on_time_query)
        on_time_count = on_time_result.scalar() or 0

        # Count total completed tasks
        completed_query = select(func.count(Task.task_id)).where(
            and_(
                Task.assignee_did == agent_did,
                Task.status == TaskStatus.COMPLETED,
                Task.created_at >= cutoff_date,
            )
        )
        completed_result = await session.execute(completed_query)
        completed_count = completed_result.scalar() or 0

        if completed_count == 0:
            return 1.0  # No tasks completed = perfect SLA (no breaches)

        return round(on_time_count / completed_count, 2)

    async def _calculate_peer_endorsements(
        self,
        session: AsyncSession,
        agent_did: str,
    ) -> float:
        """
        Calculate peer endorsement score.
        
        Formula: normalize(verified_capability_count, max=100) mapped to 0-1
        
        Args:
            session: Database session
            agent_did: Agent DID
            
        Returns:
            Peer endorsement score (0.0 - 1.0)
        """
        # Count verified capabilities
        query = select(func.count(Capability.capability_id)).where(
            and_(
                Capability.agent_did == agent_did,
                Capability.status == CapabilityStatus.VERIFIED,
            )
        )
        result = await session.execute(query)
        endorsement_count = result.scalar() or 0

        # Normalize to [0, 1] with max at MAX_ENDORSEMENTS
        normalized = min(endorsement_count / self.MAX_ENDORSEMENTS, 1.0)

        return round(normalized, 2)

    async def _calculate_audit_transparency(
        self,
        session: AsyncSession,
        agent_did: str,
    ) -> float:
        """
        Calculate audit transparency score.
        
        Formula: audit_entries / expected_entries (completeness)
        Expected entries = 1 per completed task + 1 per capability verification
        
        Args:
            session: Database session
            agent_did: Agent DID
            
        Returns:
            Audit transparency score (0.0 - 1.0)
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.TASK_WINDOW_DAYS)

        # Count actual audit entries
        audit_query = select(func.count(AuditLog.id)).where(
            and_(
                AuditLog.agent_did == agent_did,
                AuditLog.created_at >= cutoff_date,
            )
        )
        audit_result = await session.execute(audit_query)
        actual_entries = audit_result.scalar() or 0

        # Calculate expected entries (completed tasks + verified capabilities)
        task_query = select(func.count(Task.task_id)).where(
            and_(
                Task.assignee_did == agent_did,
                Task.status == TaskStatus.COMPLETED,
                Task.created_at >= cutoff_date,
            )
        )
        task_result = await session.execute(task_query)
        completed_tasks = task_result.scalar() or 0

        cap_query = select(func.count(Capability.capability_id)).where(
            and_(
                Capability.agent_did == agent_did,
                Capability.status == CapabilityStatus.VERIFIED,
                Capability.verified_at >= cutoff_date,
            )
        )
        cap_result = await session.execute(cap_query)
        verified_caps = cap_result.scalar() or 0

        expected_entries = completed_tasks + verified_caps

        if expected_entries == 0:
            return 1.0  # No activity = perfect transparency

        transparency = min(actual_entries / expected_entries, 1.0)

        return round(transparency, 2)

    async def _calculate_security_record(
        self,
        session: AsyncSession,
        agent_did: str,
    ) -> float:
        """
        Calculate security record score.
        
        Formula: 1.0 - (security_incidents * 0.1) clamped to [0, 1]
        Each incident reduces score by 0.1
        
        Args:
            session: Database session
            agent_did: Agent DID
            
        Returns:
            Security record score (0.0 - 1.0)
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.TASK_WINDOW_DAYS)

        # Count security incidents
        query = select(func.count(SecurityIncident.id)).where(
            and_(
                SecurityIncident.agent_did == agent_did,
                SecurityIncident.created_at >= cutoff_date,
            )
        )
        result = await session.execute(query)
        incident_count = result.scalar() or 0

        # Each incident reduces score by 0.1
        security_score = 1.0 - (incident_count * 0.1)

        # Clamp to [0, 1]
        security_score = max(0.0, min(1.0, security_score))

        return round(security_score, 2)

    async def _update_trust_score(
        self,
        session: AsyncSession,
        agent_did: str,
        trust_score: float,
        execution_success: float,
        sla_compliance: float,
        peer_endorsements: float,
        audit_transparency: float,
        security_record: float,
    ):
        """
        Atomically update trust score in database.
        
        Updates both agents table and agent_trust_breakdown table.
        
        Args:
            session: Database session
            agent_did: Agent DID
            trust_score: Calculated trust score
            execution_success: Execution success factor
            sla_compliance: SLA compliance factor
            peer_endorsements: Peer endorsements factor
            audit_transparency: Audit transparency factor
            security_record: Security record factor
        """
        # Update agents table
        agent_query = select(Agent).where(Agent.agent_did == agent_did)
        agent_result = await session.execute(agent_query)
        agent = agent_result.scalar_one()
        
        agent.trust_score = trust_score
        agent.updated_at = datetime.utcnow()

        # Update or create trust breakdown
        breakdown_query = select(AgentTrustBreakdown).where(
            AgentTrustBreakdown.agent_did == agent_did
        )
        breakdown_result = await session.execute(breakdown_query)
        breakdown = breakdown_result.scalar_one_or_none()

        if breakdown is None:
            breakdown = AgentTrustBreakdown(agent_did=agent_did)
            session.add(breakdown)

        breakdown.execution_success = execution_success
        breakdown.sla_compliance = sla_compliance
        breakdown.peer_endorsements = peer_endorsements
        breakdown.audit_transparency = audit_transparency
        breakdown.security_record = security_record
        breakdown.updated_at = datetime.utcnow()

    async def _emit_trust_update_event(
        self,
        agent_did: str,
        trust_score: float,
        breakdown: dict,
    ):
        """
        Emit WebSocket event for trust score update.
        
        Args:
            agent_did: Agent DID
            trust_score: New trust score
            breakdown: Trust score breakdown
        """
        event_payload = {
            "type": "TRUST_UPDATE",
            "agent_did": agent_did,
            "trust_score": trust_score,
            "breakdown": breakdown,
            "timestamp": datetime.utcnow().isoformat(),
        }

        await self.ws_manager.send_to_agent(agent_did, event_payload)

    async def _log_recalculation(
        self,
        session: AsyncSession,
        agent_did: str,
        trust_score: float,
    ):
        """
        Log trust score recalculation to audit log.
        
        Args:
            session: Database session
            agent_did: Agent DID
            trust_score: New trust score
        """
        audit_entry = AuditLog(
            agent_did=agent_did,
            entry_type=AuditEntryType.TRUST_UPDATE,
            description=f"Trust score recalculated: {trust_score:.2f}",
            metadata={
                "trust_score": trust_score,
                "recalculation_time": datetime.utcnow().isoformat(),
            },
        )

        session.add(audit_entry)
```

## File: src/monitoring/health_checks.py

```python
"""
Platform Health Check Service for AgentX
Monitors critical system components and metrics
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_async_session
from src.monitoring.sla_monitor import get_sla_monitor

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status enum."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth:
    """Health status for a single component."""
    
    def __init__(
        self,
        name: str,
        status: HealthStatus,
        message: str = "",
        latency_ms: Optional[float] = None,
        metadata: Optional[dict] = None,
    ):
        self.name = name
        self.status = status
        self.message = message
        self.latency_ms = latency_ms
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
        }
        if self.latency_ms is not None:
            result["latency_ms"] = round(self.latency_ms, 2)
        if self.metadata:
            result["metadata"] = self.metadata
        return result


class HealthCheckService:
    """
    Service for checking platform health.
    
    Monitors:
    - Database connectivity
    - Redis connectivity
    - SLA breach rate
    - Trust score calculation drift
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        sla_breach_threshold: float = 0.02,  # 2%
        trust_drift_threshold: float = 0.01,
    ):
        """
        Initialize health check service.
        
        Args:
            redis_url: Redis connection URL
            sla_breach_threshold: Alert threshold for SLA breach rate
            trust_drift_threshold: Alert threshold for trust score drift
        """
        self.redis_url = redis_url
        self.sla_breach_threshold = sla_breach_threshold
        self.trust_drift_threshold = trust_drift_threshold

    async def check_all(self) -> dict:
        """
        Run all health checks and return aggregated status.
        
        Returns:
            Dictionary with overall status and component statuses
        """
        components = []

        # Database check
        db_health = await self.check_db_connection()
        components.append(db_health)

        # Redis check
        redis_health = await self.check_redis_connection()
        components.append(redis_health)

        # SLA breach rate check
        sla_health = await self.check_sla_breach_rate()
        components.append(sla_health)

        # Trust score drift check
        trust_health = await self.check_trust_score_drift()
        components.append(trust_health)

        # Determine overall status
        overall_status = self._aggregate_status(components)

        return {
            "status": overall_status.value,
            "timestamp": datetime.utcnow().isoformat(),
            "components": [c.to_dict() for c in components],
        }

    async def check_db_connection(self) -> ComponentHealth:
        """
        Check database connectivity and latency.
        
        Returns:
            ComponentHealth for database
        """
        start_time = datetime.utcnow()
        
        try:
            async with get_async_session() as session:
                await session.execute(text("SELECT 1"))
                
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            if latency > 100:
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.DEGRADED,
                    message=f"Database latency high: {latency:.2f}ms",
                    latency_ms=latency,
                )
            
            return ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                message="Database connection healthy",
                latency_ms=latency,
            )
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Database connection failed: {str(e)}",
            )

    async def check_redis_connection(self) -> ComponentHealth:
        """
        Check Redis connectivity and latency.
        
        Returns:
            ComponentHealth for Redis
        """
        start_time = datetime.utcnow()
        
        try:
            redis_client = await aioredis.from_url(self.redis_url)
            await redis_client.ping()
            await redis_client.close()
            
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            if latency > 50:
                return ComponentHealth(
                    name="redis",
                    status=HealthStatus.DEGRADED,
                    message=f"Redis latency high: {latency:.2f}ms",
                    latency_ms=latency,
                )
            
            return ComponentHealth(
                name="redis",
                status=HealthStatus.HEALTHY,
                message="Redis connection healthy",
                latency_ms=latency,
            )
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return ComponentHealth(
                name="redis",
                status=HealthStatus.UNHEALTHY,
                message=f"Redis connection failed: {str(e)}",
            )

    async def check_sla_breach_rate(self) -> ComponentHealth:
        """
        Check SLA breach rate and alert if above threshold.
        
        Returns:
            ComponentHealth for SLA monitoring
        """
        try:
            async with get_async_session() as session:
                sla_monitor = get_sla_monitor()
                stats = await sla_monitor.get_breach_statistics(session, time_window_days=7)
                
                breach_rate = stats["breach_rate"]
                
                metadata = {
                    "breach_rate": f"{breach_rate * 100:.2f}%",
                    "total_breaches": stats["total_breaches"],
                    "total_tasks": stats["total_tasks"],
                }
                
                if breach_rate > self.sla_breach_threshold:
                    return ComponentHealth(
                        name="sla_monitoring",
                        status=HealthStatus.DEGRADED,
                        message=f"SLA breach rate above threshold: {breach_rate * 100:.2f}% > {self.sla_breach_threshold * 100}%",
                        metadata=metadata,
                    )
                
                return ComponentHealth(
                    name="sla_monitoring",
                    status=HealthStatus.HEALTHY,
                    message=f"SLA breach rate within acceptable range: {breach_rate * 100:.2f}%",
                    metadata=metadata,
                )
        except Exception as e:
            logger.error(f"SLA breach rate check failed: {e}")
            return ComponentHealth(
                name="sla_monitoring",
                status=HealthStatus.UNHEALTHY,
                message=f"SLA monitoring check failed: {str(e)}",
            )

    async def check_trust_score_drift(self) -> ComponentHealth:
        """
        Check for trust score calculation drift.
        
        Verifies that trust score matches calculated value from breakdown.
        
        Returns:
            ComponentHealth for trust score integrity
        """
        try:
            async with get_async_session() as session:
                # Sample random agents and check trust score consistency
                query = text("""
                    SELECT 
                        a.agent_did,
                        a.trust_score,
                        atb.execution_success,
                        atb.sla_compliance,
                        atb.peer_endorsements,
                        atb.audit_transparency,
                        atb.security_record
                    FROM agents a
                    JOIN agent_trust_breakdown atb ON a.agent_did = atb.agent_did
                    ORDER BY RANDOM()
                    LIMIT 10
                """)
                
                result = await session.execute(query)
                agents = result.fetchall()
                
                max_drift = 0.0
                drift_count = 0
                
                for agent in agents:
                    calculated_score = (
                        agent.execution_success * 0.35 +
                        agent.sla_compliance * 0.25 +
                        agent.peer_endorsements * 0.20 +
                        agent.audit_transparency * 0.12 +
                        agent.security_record * 0.08
                    )
                    
                    drift = abs(calculated_score - agent.trust_score)
                    max_drift = max(max_drift, drift)
                    
                    if drift > self.trust_drift_threshold:
                        drift_count += 1
                
                metadata = {
                    "max_drift": f"{max_drift:.4f}",
                    "agents_sampled": len(agents),
                    "drift_violations": drift_count,
                }
                
                if drift_count > 0:
                    return ComponentHealth(
                        name="trust_score_integrity",
                        status=HealthStatus.DEGRADED,
                        message=f"{drift_count} agents with trust score drift > {self.trust_drift_threshold}",
                        metadata=metadata,
                    )
                
                return ComponentHealth(
                    name="trust_score_integrity",
                    status=HealthStatus.HEALTHY,
                    message=f"Trust score calculations consistent (max drift: {max_drift:.4f})",
                    metadata=metadata,
                )
        except Exception as e:
            logger.error(f"Trust score drift check failed: {e}")
            return ComponentHealth(
                name="trust_score_integrity",
                status=HealthStatus.UNHEALTHY,
                message=f"Trust score integrity check failed: {str(e)}",
            )

    def _aggregate_status(self, components: list[ComponentHealth]) -> HealthStatus:
        """
        Aggregate component statuses into overall status.
        
        Rules:
        - If any component is UNHEALTHY → overall UNHEALTHY
        - If any component is DEGRADED → overall DEGRADED
        - Otherwise → overall HEALTHY
        
        Args:
            components: List of component health statuses
            
        Returns:
            Aggregated health status
        """
        statuses = [c.status for c in components]
        
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY


# Singleton instance
_health_check_service: Optional[HealthCheckService] = None


def get_health_check_service() -> HealthCheckService:
    """Get singleton health check service instance."""
    global _health_check_service
    if _health_check_service is None:
        _health_check_service = HealthCheckService()
    return _health_check_service
```

## File: tests/test_sla_monitoring.py

```python
"""
Tests for SLA monitoring system
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from src.database.models import Task, TaskStatus, Agent, TokenBalance, TokenType
from src.monitoring.sla_monitor import SLAMonitor
from src.monitoring.trust_score_service import TrustScoreService


@pytest.mark.asyncio
async def test_breach_detected_after_deadline_passes(db_session, test_agent_factory):
    """SLA monitor should detect breaches for tasks past deadline."""
    # Setup
    agent_did = await test_agent_factory(agent_did="did:agentx:test-001")
    
    # Create overdue task
    task = Task(
        task_id="task-001",
        title="Overdue Task",
        assignee_did=agent_did,
        status=TaskStatus.IN_PROGRESS,
        deadline=datetime.utcnow() - timedelta(hours=1),  # 1 hour overdue
        sla_breached=False,
        created_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.add(task)
    await db_session.commit()
    
    # Run monitor
    monitor = SLAMonitor()
    breaches = await monitor.check_breaches(db_session)
    
    # Assert
    assert len(breaches) == 1
    assert breaches[0].task_id == "task-001"


@pytest.mark.asyncio
async def test_no_breach_for_completed_task(db_session, test_agent_factory):
    """Completed tasks should not trigger SLA breach even if past deadline."""
    # Setup
    agent_did = await test_agent_factory(agent_did="did:agentx:test-002")
    
    # Create completed overdue task
    task = Task(
        task_id="task-002",
        title="Completed Task",
        assignee_did=agent_did,
        status=TaskStatus.COMPLETED,
        deadline=datetime.utcnow() - timedelta(hours=1),
        sla_breached=False,
        created_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.add(task)
    await db_session.commit()
    
    # Run monitor
    monitor = SLAMonitor()
    breaches = await monitor.check_breaches(db_session)
    
    # Assert
    assert len(breaches) == 0


@pytest.mark.asyncio
async def test_trust_score_recalculation_weights_correct(db_session, test_agent_factory):
    """Trust score should be calculated with correct weights."""
    # Setup
    agent_did = await test_agent_factory(agent_did="did:agentx:test-003")
    
    # Create mock breakdown values (all at 0.5 for easy calculation)
    from src.database.models import AgentTrustBreakdown
    breakdown = AgentTrustBreakdown(
        agent_did=agent_did,
        execution_success=0.5,
        sla_compliance=0.5,
        peer_endorsements=0.5,
        audit_transparency=0.5,
        security_record=0.5,
    )
    db_session.add(breakdown)
    await db_session.commit()
    
    # Recalculate
    service = TrustScoreService()
    
    with patch.object(service, '_calculate_execution_success', return_value=0.5), \
         patch.object(service, '_calculate_sla_compliance', return_value=0.5), \
         patch.object(service, '_calculate_peer_endorsements', return_value=0.5), \
         patch.object(service, '_calculate_audit_transparency', return_value=0.5), \
         patch.object(service, '_calculate_security_record', return_value=0.5):
        
        trust_score = await service.recalculate(db_session, agent_did)
    
    # Expected: 0.5 * (0.35 + 0.25 + 0.20 + 0.12 + 0.08) = 0.5 * 1.0 = 0.5
    assert trust_score == 0.5


@pytest.mark.asyncio
async def test_trust_score_bounded_0_to_1(db_session, test_agent_factory):
    """Trust score should always be between 0 and 1."""
    # Setup
    agent_did = await test_agent_factory(agent_did="did:agentx:test-004")
    
    service = TrustScoreService()
    
    # Test with extreme values
    with patch.object(service, '_calculate_execution_success', return_value=2.0), \
         patch.object(service, '_calculate_sla_compliance', return_value=2.0), \
         patch.object(service, '_calculate_peer_endorsements', return_value=2.0), \
         patch.object(service, '_calculate_audit_transparency', return_value=2.0), \
         patch.object(service, '_calculate_security_record', return_value=2.0):
        
        trust_score = await service.recalculate(db_session, agent_did)
    
    # Should be clamped to 1.0
    assert trust_score == 1.0
    
    # Test with negative values
    with patch.object(service, '_calculate_execution_success', return_value=-1.0), \
         patch.object(service, '_calculate_sla_compliance', return_value=-1.0), \
         patch.object(service, '_calculate_peer_endorsements', return_value=-1.0), \
         patch.object(service, '_calculate_audit_transparency', return_value=-1.0), \
         patch.object(service, '_calculate_security_record', return_