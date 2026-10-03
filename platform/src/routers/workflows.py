from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.workflow import WorkflowCreate, WorkflowResponse
from ..services.workflows import create_workflow_record, get_workflow

router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowResponse,
)
async def create_workflow(
    body: WorkflowCreate,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Create a workflow; each step becomes a routed task requested by the caller.

    Requires a JWT (Sprint 9, S9-6a). The initiator is the JWT caller: before
    this, anyone could create workflows — and so tasks — in any agent's name.
    """
    if body.initiator_agent_did is not None and body.initiator_agent_did != agent.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="initiator_agent_did must be the authenticated agent's DID",
        )
    workflow = await create_workflow_record(
        initiator_agent_did=agent.did,
        workflow_type=body.workflow_type,
        steps=[step.model_dump() for step in body.steps],
    )
    return WorkflowResponse(**workflow)


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
)
async def get_workflow_status(workflow_id: UUID):
    workflow = await get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow not found: {workflow_id}",
        )
    return WorkflowResponse(**workflow)
