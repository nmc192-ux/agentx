"""
AgentX Platform — Subcontracting Service
═════════════════════════════════════════
Phase 19: Autonomous Agent Economies.

Allows the assigned contractor of an existing contract to spawn child
(sub-)contracts, delegating parts of their work to other agents.  The
parent–child relationship is encoded in the child contract's payload so
that no DB schema changes are required.

Public API
──────────
  spawn_subcontract(parent_contract_id, caller_did, data)
      → SubcontractResponse

Design notes
────────────
• Reads the parent contract directly via get_db() (no new service fn
  needed; avoids import cycles).
• Delegates child creation to contract_service.create_contract(), which
  handles budget escrow, ledger entries, and event publishing.
• parent_contract_id is stored inside child.payload so existing DB
  tables/columns are reused with no schema migration.
• Table name: contracts (confirmed from contract_service.py).
• Only the assigned contractor may spawn subcontracts.
• Parent must be in 'assigned' or 'submitted' status.
"""
from __future__ import annotations

import logging
from uuid import UUID

from ..database import get_db
from ..models.agent_economy import SubcontractCreate, SubcontractResponse
from ..models.contract import ContractCreate
from . import contract_service

logger = logging.getLogger(__name__)

_ALLOWED_PARENT_STATUSES = ("assigned", "submitted")


async def spawn_subcontract(
    parent_contract_id: UUID,
    caller_did: str,
    data: SubcontractCreate,
) -> SubcontractResponse:
    """
    Spawn a sub-contract under an existing parent contract.

    The caller must be the assigned contractor of the parent contract.
    A new child contract is created with contract_type='subcontract' and
    the parent_contract_id embedded in the payload.

    Args:
        parent_contract_id: UUID of the parent (master) contract.
        caller_did:         DID of the caller (must be the contractor).
        data:               SubcontractCreate payload.

    Returns:
        SubcontractResponse — the child contract plus parent_contract_id.

    Raises:
        ValueError: Parent not found, caller not contractor, or parent
                    status does not allow subcontracting.
    """
    # ── Step 1: Validate parent contract ──────────────────────────────────────
    async with get_db() as conn:
        parent_row = await conn.fetchrow(
            """
            SELECT contract_id, contractor_did, status
              FROM contracts
             WHERE contract_id = $1
            """,
            parent_contract_id,
        )

    if parent_row is None:
        raise ValueError(f"Parent contract not found: {parent_contract_id}")

    if parent_row["contractor_did"] != caller_did:
        raise ValueError(
            "Only the assigned contractor can spawn sub-contracts"
        )

    if parent_row["status"] not in _ALLOWED_PARENT_STATUSES:
        raise ValueError(
            f"Cannot sub-contract from a '{parent_row['status']}' contract; "
            f"parent must be in {_ALLOWED_PARENT_STATUSES}"
        )

    # ── Step 2: Build child payload (embed parent reference) ──────────────────
    child_payload: dict = {"parent_contract_id": str(parent_contract_id)}
    if data.payload:
        child_payload.update(data.payload)

    # ── Step 3: Create child contract ─────────────────────────────────────────
    child_create = ContractCreate(
        title=data.title,
        description=data.description,
        contract_type="subcontract",
        budget=data.budget,
        payload=child_payload,
        deadline=data.deadline,
    )

    child = await contract_service.create_contract(
        caller_did=caller_did,
        data=child_create,
    )

    logger.info(
        "subcontract_service: child contract %s spawned from parent %s by %s",
        child.contract_id, parent_contract_id, caller_did,
    )

    # ── Step 4: Return enriched response ──────────────────────────────────────
    return SubcontractResponse(
        contract_id=child.contract_id,
        creator_did=child.creator_did,
        creator_id=child.creator_id,
        contractor_did=child.contractor_did,
        contractor_id=child.contractor_id,
        title=child.title,
        description=child.description,
        contract_type=child.contract_type,
        status=child.status,
        budget=child.budget,
        escrowed_budget=child.escrowed_budget,
        deadline=child.deadline,
        payload=child.payload,
        created_at=child.created_at,
        parent_contract_id=parent_contract_id,
    )
