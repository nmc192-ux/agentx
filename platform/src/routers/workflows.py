from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from ..models.workflow import WorkflowCreate, WorkflowResponse
from ..services.workflows import create_workflow_record, get_workflow

router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowResponse,
)
async def create_workflow(body: WorkflowCreate):
    workflow = await create_workflow_record(
        initiator_agent_did=body.initiator_agent_did,
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
