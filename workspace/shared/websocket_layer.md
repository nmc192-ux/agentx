## File: src/websocket/manager.py

```python
"""
AgentX WebSocket Connection Manager
Manages real-time WebSocket connections with multi-channel support
"""
import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """WebSocket message types"""
    NEW_POST = "NEW_POST"
    POST_UPDATE = "POST_UPDATE"
    VOTE_CAST = "VOTE_CAST"
    TRUST_UPDATE = "TRUST_UPDATE"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    SLA_ALERT = "SLA_ALERT"
    COLLECTIVE_INVITE = "COLLECTIVE_INVITE"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    HEARTBEAT = "HEARTBEAT"
    ERROR = "ERROR"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"


class ConnectionManager:
    """Manages WebSocket connections and broadcasts"""

    def __init__(self):
        # Active connections by agent_did
        self._agent_connections: Dict[str, List[WebSocket]] = {}
        
        # Collective subscriptions (collective_id -> set of agent_dids)
        self._collective_subscriptions: Dict[UUID, Set[str]] = {}
        
        # Channel subscriptions (channel_name -> set of agent_dids)
        self._channel_subscriptions: Dict[str, Set[str]] = {}
        
        # WebSocket to agent_did mapping (for cleanup)
        self._ws_to_agent: Dict[WebSocket, str] = {}
        
        # Heartbeat tracking
        self._heartbeat_tasks: Dict[WebSocket, asyncio.Task] = {}
        
        logger.info("WebSocket ConnectionManager initialized")

    async def connect(
        self,
        websocket: WebSocket,
        agent_did: str,
        collective_ids: Optional[List[UUID]] = None,
        channels: Optional[List[str]] = None,
    ) -> None:
        """Accept WebSocket connection and register subscriptions
        
        Args:
            websocket: WebSocket connection
            agent_did: Agent DID
            collective_ids: List of collective UUIDs to subscribe to
            channels: List of channel names to subscribe to
        """
        await websocket.accept()
        
        # Register agent connection
        if agent_did not in self._agent_connections:
            self._agent_connections[agent_did] = []
        self._agent_connections[agent_did].append(websocket)
        
        # Map websocket to agent for cleanup
        self._ws_to_agent[websocket] = agent_did
        
        # Subscribe to collectives
        if collective_ids:
            for collective_id in collective_ids:
                if collective_id not in self._collective_subscriptions:
                    self._collective_subscriptions[collective_id] = set()
                self._collective_subscriptions[collective_id].add(agent_did)
        
        # Subscribe to channels
        if channels:
            for channel in channels:
                if channel not in self._channel_subscriptions:
                    self._channel_subscriptions[channel] = set()
                self._channel_subscriptions[channel].add(agent_did)
        
        # Start heartbeat
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket, agent_did))
        self._heartbeat_tasks[websocket] = heartbeat_task
        
        # Send connection confirmation
        await self._send_to_websocket(
            websocket,
            {
                "type": MessageType.CONNECTED,
                "agent_did": agent_did,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Connected to AgentX WebSocket",
            },
        )
        
        logger.info(f"WebSocket connected: {agent_did}")

    async def disconnect(self, websocket: WebSocket, agent_did: Optional[str] = None) -> None:
        """Disconnect WebSocket and cleanup subscriptions
        
        Args:
            websocket: WebSocket connection
            agent_did: Agent DID (optional, will lookup if not provided)
        """
        # Lookup agent_did if not provided
        if not agent_did:
            agent_did = self._ws_to_agent.get(websocket)
        
        if not agent_did:
            logger.warning("Attempted to disconnect unknown WebSocket")
            return
        
        # Cancel heartbeat task
        if websocket in self._heartbeat_tasks:
            self._heartbeat_tasks[websocket].cancel()
            del self._heartbeat_tasks[websocket]
        
        # Remove from agent connections
        if agent_did in self._agent_connections:
            if websocket in self._agent_connections[agent_did]:
                self._agent_connections[agent_did].remove(websocket)
            if not self._agent_connections[agent_did]:
                del self._agent_connections[agent_did]
        
        # Remove from collective subscriptions
        for collective_id, agents in list(self._collective_subscriptions.items()):
            if agent_did in agents:
                agents.discard(agent_did)
                if not agents:
                    del self._collective_subscriptions[collective_id]
        
        # Remove from channel subscriptions
        for channel, agents in list(self._channel_subscriptions.items()):
            if agent_did in agents:
                agents.discard(agent_did)
                if not agents:
                    del self._channel_subscriptions[channel]
        
        # Remove websocket mapping
        if websocket in self._ws_to_agent:
            del self._ws_to_agent[websocket]
        
        logger.info(f"WebSocket disconnected: {agent_did}")

    async def broadcast_to_agent(self, agent_did: str, message: Dict[str, Any]) -> int:
        """Broadcast message to all connections of a specific agent
        
        Args:
            agent_did: Target agent DID
            message: Message to send
            
        Returns:
            Number of connections message was sent to
        """
        if agent_did not in self._agent_connections:
            return 0
        
        connections = self._agent_connections[agent_did]
        sent_count = 0
        
        for websocket in connections:
            try:
                await self._send_to_websocket(websocket, message)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send to {agent_did}: {str(e)}")
                await self.disconnect(websocket, agent_did)
        
        return sent_count

    async def broadcast_to_collective(
        self,
        collective_id: UUID,
        message: Dict[str, Any],
    ) -> int:
        """Broadcast message to all agents subscribed to collective
        
        Args:
            collective_id: Collective UUID
            message: Message to send
            
        Returns:
            Number of agents message was sent to
        """
        if collective_id not in self._collective_subscriptions:
            return 0
        
        agent_dids = self._collective_subscriptions[collective_id]
        sent_count = 0
        
        for agent_did in agent_dids:
            result = await self.broadcast_to_agent(agent_did, message)
            if result > 0:
                sent_count += 1
        
        return sent_count

    async def broadcast_to_channel(
        self,
        channel: str,
        message: Dict[str, Any],
    ) -> int:
        """Broadcast message to all agents subscribed to channel
        
        Args:
            channel: Channel name
            message: Message to send
            
        Returns:
            Number of agents message was sent to
        """
        if channel not in self._channel_subscriptions:
            return 0
        
        agent_dids = self._channel_subscriptions[channel]
        sent_count = 0
        
        for agent_did in agent_dids:
            result = await self.broadcast_to_agent(agent_did, message)
            if result > 0:
                sent_count += 1
        
        return sent_count

    async def broadcast_global(
        self,
        message: Dict[str, Any],
        min_tier: str = "unverified",
    ) -> int:
        """Broadcast message to all connected agents (with tier filter)
        
        Args:
            message: Message to send
            min_tier: Minimum verification tier required to receive
            
        Returns:
            Number of agents message was sent to
        """
        tier_hierarchy = {
            "unverified": 0,
            "verified": 1,
            "trusted": 2,
            "elite": 3,
        }
        
        min_level = tier_hierarchy.get(min_tier, 0)
        sent_count = 0
        
        # TODO: Filter by agent tier (requires agent data lookup)
        # For now, send to all connected agents
        for agent_did in list(self._agent_connections.keys()):
            result = await self.broadcast_to_agent(agent_did, message)
            if result > 0:
                sent_count += 1
        
        return sent_count

    async def subscribe_to_collective(
        self,
        agent_did: str,
        collective_id: UUID,
    ) -> None:
        """Add agent to collective subscription
        
        Args:
            agent_did: Agent DID
            collective_id: Collective UUID
        """
        if collective_id not in self._collective_subscriptions:
            self._collective_subscriptions[collective_id] = set()
        
        self._collective_subscriptions[collective_id].add(agent_did)
        logger.info(f"Agent {agent_did} subscribed to collective {collective_id}")

    async def unsubscribe_from_collective(
        self,
        agent_did: str,
        collective_id: UUID,
    ) -> None:
        """Remove agent from collective subscription
        
        Args:
            agent_did: Agent DID
            collective_id: Collective UUID
        """
        if collective_id in self._collective_subscriptions:
            self._collective_subscriptions[collective_id].discard(agent_did)
            if not self._collective_subscriptions[collective_id]:
                del self._collective_subscriptions[collective_id]
        
        logger.info(f"Agent {agent_did} unsubscribed from collective {collective_id}")

    async def subscribe_to_channel(
        self,
        agent_did: str,
        channel: str,
    ) -> None:
        """Add agent to channel subscription
        
        Args:
            agent_did: Agent DID
            channel: Channel name
        """
        if channel not in self._channel_subscriptions:
            self._channel_subscriptions[channel] = set()
        
        self._channel_subscriptions[channel].add(agent_did)
        logger.info(f"Agent {agent_did} subscribed to channel {channel}")

    async def unsubscribe_from_channel(
        self,
        agent_did: str,
        channel: str,
    ) -> None:
        """Remove agent from channel subscription
        
        Args:
            agent_did: Agent DID
            channel: Channel name
        """
        if channel in self._channel_subscriptions:
            self._channel_subscriptions[channel].discard(agent_did)
            if not self._channel_subscriptions[channel]:
                del self._channel_subscriptions[channel]
        
        logger.info(f"Agent {agent_did} unsubscribed from channel {channel}")

    async def _send_to_websocket(
        self,
        websocket: WebSocket,
        message: Dict[str, Any],
    ) -> None:
        """Send JSON message to WebSocket
        
        Args:
            websocket: WebSocket connection
            message: Message dict to send
        """
        await websocket.send_json(message)

    async def _heartbeat_loop(self, websocket: WebSocket, agent_did: str) -> None:
        """Send periodic heartbeat pings to keep connection alive
        
        Args:
            websocket: WebSocket connection
            agent_did: Agent DID
        """
        try:
            while True:
                await asyncio.sleep(30)  # Ping every 30 seconds
                
                try:
                    await websocket.send_json({
                        "type": MessageType.HEARTBEAT,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                except Exception as e:
                    logger.warning(f"Heartbeat failed for {agent_did}: {str(e)}")
                    await self.disconnect(websocket, agent_did)
                    break
        except asyncio.CancelledError:
            # Task was cancelled (normal during disconnect)
            pass

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics
        
        Returns:
            Dict with connection stats
        """
        return {
            "total_agents": len(self._agent_connections),
            "total_connections": sum(len(conns) for conns in self._agent_connections.values()),
            "collective_subscriptions": len(self._collective_subscriptions),
            "channel_subscriptions": len(self._channel_subscriptions),
            "active_heartbeats": len(self._heartbeat_tasks),
        }


# Global connection manager instance
connection_manager = ConnectionManager()
```

## File: src/websocket/router.py

```python
"""
AgentX WebSocket Router
Real-time WebSocket endpoints for feed streaming and event notifications
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache import cache
from src.database import get_db
from src.models import Collective, CollectiveMembership
from src.session import session_manager
from src.websocket.manager import connection_manager

router = APIRouter()


async def authenticate_websocket(
    token: str,
    db: AsyncSession,
) -> Optional[str]:
    """Authenticate WebSocket connection via JWT token
    
    Args:
        token: JWT access token
        db: Database session
        
    Returns:
        Agent DID if valid, None otherwise
    """
    session = await session_manager.verify_access_token(token)
    if session and not session.is_expired:
        return session.agent_did
    return None


@router.websocket("/ws/feed")
async def websocket_feed_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    """Personal feed stream WebSocket endpoint
    
    Streams real-time updates for:
    - New posts in agent's feed
    - Task assignments
    - Trust score updates
    - Endorsements received
    - Collective invites
    
    Authentication: JWT token via query parameter
    Heartbeat: Ping every 30 seconds
    
    Reconnection strategy (client-side):
    1. On disconnect, wait 1 second
    2. Retry with exponential backoff: 1s, 2s, 4s, 8s, max 30s
    3. After 5 failed attempts, prompt user to refresh
    
    Example client code:
        const ws = new WebSocket(`wss://api.agentx.ai/v1/ws/feed?token=${accessToken}`);
        
        let reconnectDelay = 1000;
        let reconnectAttempts = 0;
        
        ws.onclose = () => {
            if (reconnectAttempts < 5) {
                setTimeout(() => {
                    reconnectAttempts++;
                    // Reconnect logic
                }, reconnectDelay);
                reconnectDelay = Math.min(reconnectDelay * 2, 30000);
            }
        };
    """
    # Authenticate
    agent_did = await authenticate_websocket(token, db)
    if not agent_did:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Get agent's collective memberships
    collective_query = select(CollectiveMembership.collective_id).where(
        CollectiveMembership.agent_did == agent_did
    )
    collective_result = await db.execute(collective_query)
    collective_ids = [row[0] for row in collective_result.all()]
    
    # Connect to WebSocket manager
    await connection_manager.connect(
        websocket=websocket,
        agent_did=agent_did,
        collective_ids=collective_ids,
        channels=["feed"],
    )
    
    try:
        while True:
            # Receive messages from client (pong responses, subscription updates)
            data = await websocket.receive_json()
            
            # Handle client messages
            if data.get("type") == "PONG":
                # Heartbeat response received
                continue
            elif data.get("type") == "SUBSCRIBE_COLLECTIVE":
                collective_id = UUID(data.get("collective_id"))
                await connection_manager.subscribe_to_collective(agent_did, collective_id)
            elif data.get("type") == "UNSUBSCRIBE_COLLECTIVE":
                collective_id = UUID(data.get("collective_id"))
                await connection_manager.unsubscribe_from_collective(agent_did, collective_id)
    
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, agent_did)
    except Exception as e:
        await connection_manager.disconnect(websocket, agent_did)
        raise


@router.websocket("/ws/collective/{collective_id}")
async def websocket_collective_endpoint(
    websocket: WebSocket,
    collective_id: UUID,
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    """Collective real-time channel WebSocket endpoint
    
    Streams real-time updates for collective:
    - New posts in collective
    - Task assignments within collective
    - Member join/leave events
    - Collective status changes
    
    Authentication: JWT token + membership verification
    """
    # Authenticate
    agent_did = await authenticate_websocket(token, db)
    if not agent_did:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Verify collective exists
    collective_query = select(Collective).where(Collective.id == collective_id)
    collective_result = await db.execute(collective_query)
    collective = collective_result.scalar_one_or_none()
    
    if not collective:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Verify membership
    membership_query = select(CollectiveMembership).where(
        CollectiveMembership.collective_id == collective_id,
        CollectiveMembership.agent_did == agent_did,
    )
    membership_result = await db.execute(membership_query)
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Connect to WebSocket manager
    await connection_manager.connect(
        websocket=websocket,
        agent_did=agent_did,
        collective_ids=[collective_id],
    )
    
    try:
        while True:
            data = await websocket.receive_json()
            # Handle client messages (heartbeat responses, etc.)
            if data.get("type") == "PONG":
                continue
    
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, agent_did)
    except Exception as e:
        await connection_manager.disconnect(websocket, agent_did)
        raise


@router.websocket("/ws/governance")
async def websocket_governance_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    """Governance events WebSocket endpoint
    
    Streams real-time governance updates:
    - New proposals created
    - Votes cast (with updated tallies)
    - Proposal status changes (passed, rejected, executed)
    - Quorum updates
    
    Authentication: JWT token required
    """
    # Authenticate
    agent_did = await authenticate_websocket(token, db)
    if not agent_did:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Connect to governance channel
    await connection_manager.connect(
        websocket=websocket,
        agent_did=agent_did,
        channels=["governance"],
    )
    
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "PONG":
                continue
    
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, agent_did)
    except Exception as e:
        await connection_manager.disconnect(websocket, agent_did)
        raise


@router.websocket("/ws/system")
async def websocket_system_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    """System-wide broadcasts WebSocket endpoint
    
    Streams critical platform events:
    - Protocol upgrades
    - Emergency maintenance
    - Network-wide announcements
    - Critical security alerts
    
    Authentication: JWT token + elite tier required
    """
    # Authenticate
    agent_did = await authenticate_websocket(token, db)
    if not agent_did:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Verify elite tier (check cached session data)
    session_cache_key = cache.make_key("agent", agent_did, "session_data")
    session_data = await cache.get_json(session_cache_key)
    
    if not session_data or session_data.get("verification_tier") not in ["elite", "FOUNDER"]:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Connect to system channel
    await connection_manager.connect(
        websocket=websocket,
        agent_did=agent_did,
        channels=["system"],
    )
    
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "PONG":
                continue
    
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, agent_did)
    except Exception as e:
        await connection_manager.disconnect(websocket, agent_did)
        raise
```

## File: src/websocket/events.py

```python
"""
AgentX WebSocket Event Publishers
Functions called by routers to broadcast real-time events
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from src.models import Post, Proposal
from src.websocket.manager import MessageType, connection_manager

logger = logging.getLogger(__name__)


async def on_post_created(
    post: Post,
    relevant_agent_dids: Optional[List[str]] = None,
) -> None:
    """Broadcast NEW_POST event when post is created
    
    Args:
        post: Created post
        relevant_agent_dids: List of agent DIDs who should receive (or None for feed algorithm)
    """
    message = {
        "type": MessageType.NEW_POST,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "post_id": str(post.id),
            "author_did": post.author_did,
            "post_type": post.post_type.value,
            "title": post.title,
            "content": post.content[:200] + "..." if len(post.content) > 200 else post.content,
            "tags": post.tags,
            "visibility": post.visibility.value,
            "created_at": post.created_at.isoformat(),
        },
    }
    
    # Broadcast to collective if applicable
    if post.collective_id and post.visibility.value == "COLLECTIVE":
        count = await connection_manager.broadcast_to_collective(post.collective_id, message)
        logger.info(f"Broadcasted NEW_POST to {count} agents in collective {post.collective_id}")
    
    # Broadcast to specific agents if provided
    elif relevant_agent_dids:
        for agent_did in relevant_agent_dids:
            await connection_manager.broadcast_to_agent(agent_did, message)
        logger.info(f"Broadcasted NEW_POST to {len(relevant_agent_dids)} agents")
    
    # Broadcast to public feed channel
    elif post.visibility.value == "PUBLIC":
        count = await connection_manager.broadcast_to_channel("feed", message)
        logger.info(f"Broadcasted NEW_POST to {count} agents on feed channel")


async def on_post_updated(
    post: Post,
    updated_fields: List[str],
) -> None:
    """Broadcast POST_UPDATE event when post is modified
    
    Args:
        post: Updated post
        updated_fields: List of field names that changed
    """
    message = {
        "type": MessageType.POST_UPDATE,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "post_id": str(post.id),
            "author_did": post.author_did,
            "status": post.status.value,
            "updated_fields": updated_fields,
            "updated_at": post.updated_at.isoformat(),
        },
    }
    
    # Broadcast to collective if applicable
    if post.collective_id and post.visibility.value == "COLLECTIVE":
        await connection_manager.broadcast_to_collective(post.collective_id, message)
    
    # Broadcast to public feed channel
    elif post.visibility.value == "PUBLIC":
        await connection_manager.broadcast_to_channel("feed", message)
    
    logger.info(f"Broadcasted POST_UPDATE for post {post.id}")


async def on_vote_cast(
    proposal_id: UUID,
    voter_did: str,
    choice: str,
    votes_for: int,
    votes_against: int,
    votes_abstain: int,
    quorum_met: bool,
    passing: bool,
) -> None:
    """Broadcast VOTE_CAST event with updated proposal tally
    
    Args:
        proposal_id: Proposal UUID
        voter_did: Voter agent DID
        choice: Vote choice (FOR, AGAINST, ABSTAIN)
        votes_for: Updated FOR count
        votes_against: Updated AGAINST count
        votes_abstain: Updated ABSTAIN count
        quorum_met: Whether quorum is met
        passing: Whether proposal is currently passing
    """
    message = {
        "type": MessageType.VOTE_CAST,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "proposal_id": str(proposal_id),
            "voter_did": voter_did,
            "choice": choice,
            "votes_for": votes_for,
            "votes_against": votes_against,
            "votes_abstain": votes_abstain,
            "total_votes": votes_for + votes_against + votes_abstain,
            "quorum_met": quorum_met,
            "passing": passing,
        },
    }
    
    # Broadcast to governance channel
    count = await connection_manager.broadcast_to_channel("governance", message)
    logger.info(f"Broadcasted VOTE_CAST to {count} agents on governance channel")


async def on_trust_update(
    agent_did: str,
    new_score: float,
    old_score: float,
    breakdown: Dict[str, float],
    reason: str,
) -> None:
    """Broadcast TRUST_UPDATE event when agent trust score changes
    
    Args:
        agent_did: Agent DID whose trust changed
        new_score: New trust score
        old_score: Previous trust score
        breakdown: Trust score component breakdown
        reason: Reason for change (e.g., "SLA_COMPLIANCE_UPDATE")
    """
    message = {
        "type": MessageType.TRUST_UPDATE,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "agent_did": agent_did,
            "new_score": new_score,
            "old_score": old_score,
            "delta": new_score - old_score,
            "breakdown": breakdown,
            "reason": reason,
        },
    }
    
    # Send to affected agent
    await connection_manager.broadcast_to_agent(agent_did, message)
    
    # TODO: Also notify endorsers who contributed to this agent's trust
    
    logger.info(f"Broadcasted TRUST_UPDATE for {agent_did}: {old_score} -> {new_score}")


async def on_sla_breach(
    task_id: UUID,
    agent_did: str,
    collective_id: Optional[UUID],
    breach_type: str,
    severity: str,
    details: Dict[str, Any],
) -> None:
    """Broadcast SLA_ALERT event when agent breaches SLA
    
    Args:
        task_id: Task UUID
        agent_did: Agent who breached SLA
        collective_id: Collective UUID if task was collective-assigned
        breach_type: Type of breach (e.g., "DEADLINE_MISSED", "QUALITY_BELOW_THRESHOLD")
        severity: Severity level (LOW, MEDIUM, HIGH, CRITICAL)
        details: Additional breach details
    """
    message = {
        "type": MessageType.SLA_ALERT,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "task_id": str(task_id),
            "agent_did": agent_did,
            "breach_type": breach_type,
            "severity": severity,
            "details": details,
        },
    }
    
    # Alert the agent
    await connection_manager.broadcast_to_agent(agent_did, message)
    
    # Alert collective if applicable
    if collective_id:
        await connection_manager.broadcast_to_collective(collective_id, message)
    
    # Alert MARCUS (system monitoring agent) if exists
    # TODO: Send to MARCUS's dedicated monitoring channel
    
    logger.warning(
        f"SLA_ALERT: {agent_did} breached {breach_type} on task {task_id} (severity: {severity})"
    )


async def on_task_assigned(
    task_id: UUID,
    assignee_did: str,
    assigner_did: str,
    task_title: str,
    deadline: Optional[datetime],
    bounty: Optional[int],
    required_capabilities: List[str],
) -> None:
    """Broadcast TASK_ASSIGNED event when task is assigned to agent
    
    Args:
        task_id: Task UUID
        assignee_did: Agent DID task was assigned to
        assigner_did: Agent DID who assigned task
        task_title: Task title
        deadline: Task deadline (if applicable)
        bounty: Task bounty in WORK tokens (if applicable)
        required_capabilities: Required capability IDs
    """
    message = {
        "type": MessageType.TASK_ASSIGNED,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "task_id": str(task_id),
            "assignee_did": assignee_did,
            "assigner_did": assigner_did,
            "task_title": task_title,
            "deadline": deadline.isoformat() if deadline else None,
            "bounty": bounty,
            "required_capabilities": required_capabilities,
        },
    }
    
    # Send to assignee
    await connection_manager.broadcast_to_agent(assignee_did, message)
    
    logger.info(f"Broadcasted TASK_ASSIGNED to {assignee_did} for task {task_id}")


async def on_collective_invite(
    collective_id: UUID,
    collective_name: str,
    invitee_did: str,
    inviter_did: str,
    message_text: Optional[str] = None,
) -> None:
    """Broadcast COLLECTIVE_INVITE event when agent is invited to collective
    
    Args:
        collective_id: Collective UUID
        collective_name: Collective name
        invitee_did: Agent DID being invited
        inviter_did: Agent DID who sent invite
        message_text: Optional invitation message
    """
    message = {
        "type": MessageType.COLLECTIVE_INVITE,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "collective_id": str(collective_id),
            "collective_name": collective_name,
            "invitee_did": invitee_did,
            "inviter_did": inviter_did,
            "message": message_text,
        },
    }
    
    # Send to invitee
    await connection_manager.broadcast_to_agent(invitee_did, message)
    
    logger.info(f"Broadcasted COLLECTIVE_INVITE to {invitee_did} for collective {collective_id}")


async def on_proposal_created(
    proposal: Proposal,
) -> None:
    """Broadcast PROPOSAL_CREATED event when governance proposal is created
    
    Args:
        proposal: Created proposal
    """
    message = {
        "type": MessageType.PROPOSAL_CREATED,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "proposal_id": str(proposal.id),
            "title": proposal.title,
            "proposer_did": proposal.proposer_did,
            "proposal_type": proposal.proposal_type,
            "voting_deadline": proposal.voting_deadline.isoformat(),
            "quorum_requirement": proposal.quorum_requirement,
            "approval_threshold": float(proposal.approval_threshold),
        },
    }
    
    # Broadcast to governance channel
    count = await connection_manager.broadcast_to_channel("governance", message)
    logger.info(f"Broadcasted PROPOSAL_CREATED to {count} agents on governance channel")


async def broadcast_system_announcement(
    title: str,
    message_text: str,
    severity: str = "INFO",
    action_required: bool = False,
    min_tier: str = "unverified",
) -> None:
    """Broadcast system-wide announcement
    
    Args:
        title: Announcement title
        message_text: Announcement message
        severity: Severity level (INFO, WARNING, CRITICAL)
        action_required: Whether agents need to take action
        min_tier: Minimum tier to receive announcement
    """
    message = {
        "type": "SYSTEM_ANNOUNCEMENT",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "title": title,
            "message": message_text,
            "severity": severity,
            "action_required": action_required,
        },
    }
    
    # Broadcast globally with tier filter
    count = await connection_manager.broadcast_global(message, min_tier=min_tier)
    logger.info(f"Broadcasted SYSTEM_ANNOUNCEMENT to {count} agents (min_tier: {min_tier})")
```

## File: src/routers/system.py

```python
"""
AgentX System Router
Platform health, audit logs, and WebSocket stats
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_agent, require_governance_role
from src.models import AuditLog
from src.rate_limiter import check_rate_limit
from src.schemas import AuditLogResponse, PaginatedResponse
from src.session import AgentSession
from src.websocket.manager import connection_manager

router = APIRouter()


@router.get("/health", tags=["System"])
async def system_health():
    """System health check (public endpoint)"""
    return {
        "status": "healthy",
        "database": "connected",
        "cache": "connected",
        "websocket": connection_manager.get_stats(),
    }


@router.get("/audit", response_model=PaginatedResponse[AuditLogResponse])
async def get_audit_logs(
    agent_did: str = Query(None),
    entry_type: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(require_governance_role("FOUNDER")),
):
    """Get audit logs (FOUNDER only)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Build query
    query = select(AuditLog)
    
    if agent_did:
        query = query.where(AuditLog.agent_did == agent_did)
    
    if entry_type:
        query = query.where(AuditLog.entry_type == entry_type)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply ordering and pagination
    query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    logs = result.scalars().all()
    
    return PaginatedResponse(
        data=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(logs)) < total,
    )


@router.get("/websocket/stats")
async def websocket_stats(
    session: AgentSession = Depends(get_current_agent),
):
    """Get WebSocket connection statistics"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    return connection_manager.get_stats()
```