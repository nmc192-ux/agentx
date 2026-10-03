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
• The parent contract row is locked (``SELECT … FOR UPDATE``) and the child
  is created in the SAME transaction (Sprint 9, S9-7c). The parent's status
  and contractor are therefore read under the lock: a parent that is being
  completed, disputed or cancelled at the same moment either finishes first
  (and the sub-contract is refused) or waits until the child exists.
• The child is an ordinary contract: its budget is escrowed from the
  caller's own wallet by contract_service (no funds → no sub-contract).
• parent_contract_id is stored inside child.payload so existing DB
  tables/columns are reused with no schema migration. The caller's own
  payload cannot overwrite that key.
• Table name: contracts (confirmed from contract_service.py).
• Only the assigned contractor may spawn subcontracts.
• Parent must be in 'assigned' or 'submitted' status.
• Errors: PermissionError → 403, ContractConflictError → 409, other
  ValueError → 404 ("not found") or 400. See routers/agent_economy.py.
"""
from __future__ import annotations

import logging
from uuid import UUID

from ..database import transaction
from ..models.agent_economy import SubcontractCreate, SubcontractResponse
from ..models.contract import ContractCreate
from . import contract_service
from .contract_service import ContractConflictError

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
        ValueError:            parent not found, or the caller's wallet cannot
                               cover the child's budget.
        PermissionError:       caller is not the parent's assigned contractor.
        ContractConflictError: parent status does not allow subcontracting.
    """
    # The caller's payload first, the parent reference last: a payload that
    # carries its own "parent_contract_id" cannot point the child elsewhere.
    child_payload: dict = dict(data.payload or {})
    child_payload["parent_contract_id"] = str(parent_contract_id)

    child_create = ContractCreate(
        title=data.title,
        description=data.description,
        contract_type="subcontract",
        budget=data.budget,
        payload=child_payload,
        deadline=data.deadline,
    )

    async with transaction() as conn:
        # Lock the parent, then validate and create the child under that lock.
        parent_row = await conn.fetchrow(
            """
            SELECT contract_id, contractor_did, status
              FROM contracts
             WHERE contract_id = $1
               FOR UPDATE
            """,
            parent_contract_id,
        )

        if parent_row is None:
            raise ValueError(f"Parent contract not found: {parent_contract_id}")

        if parent_row["contractor_did"] is None or parent_row["contractor_did"] != caller_did:
            raise PermissionError(
                "Only the assigned contractor can spawn sub-contracts"
            )

        if parent_row["status"] not in _ALLOWED_PARENT_STATUSES:
            raise ContractConflictError(
                f"Cannot sub-contract from a '{parent_row['status']}' contract; "
                f"parent must be in {_ALLOWED_PARENT_STATUSES}"
            )

        child = await contract_service.create_contract_in_transaction(
            conn, caller_did, child_create,
        )

    await contract_service.announce_contract_created(child)

    logger.info(
        "subcontract_service: child contract %s spawned from parent %s by %s",
        child.contract_id, parent_contract_id, caller_did,
    )

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
