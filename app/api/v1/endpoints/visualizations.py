"""Visualization history REST API endpoints."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.response import ApiResponse
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.services.viz_state_manager import VizStateManager


router = APIRouter()


@router.get("/history", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def get_visualization_history(
    limit: int = Query(default=50, ge=1, le=100, description="Max results to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get visualization history for the current user.

    Returns a paginated list of past visualizations with metadata.
    """
    # Create a state manager for the query (session_id not needed for history)
    state_manager = VizStateManager(session_id="")

    history = await state_manager.get_history(
        db=db,
        user_id=current_user["id"],
        limit=limit,
        offset=offset,
    )

    return ApiResponse(
        success=True,
        message="Visualization history retrieved",
        data={
            "visualizations": history,
            "count": len(history),
            "limit": limit,
            "offset": offset,
        }
    )


@router.get("/{viz_id}", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def get_visualization(
    viz_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific visualization by ID.

    Returns full visualization data including chart data for download/replay.
    """
    state_manager = VizStateManager(session_id="")

    viz = await state_manager.get_viz_by_id(
        db=db,
        viz_id=viz_id,
        user_id=current_user["id"],
    )

    if not viz:
        return ApiResponse(
            success=False,
            message="Visualization not found",
            data=None,
        )

    # Mark as viewed
    await state_manager.mark_viewed(db=db, viz_id=viz_id, user_id=current_user["id"])

    return ApiResponse(
        success=True,
        message="Visualization retrieved",
        data=viz,
    )


@router.post("/{viz_id}/interact", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def mark_visualization_interacted(
    viz_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a visualization as interacted.

    Call this when the user clicks explore_next or otherwise engages
    with the visualization beyond just viewing.
    """
    state_manager = VizStateManager(session_id="")

    success = await state_manager.mark_interacted(
        db=db,
        viz_id=viz_id,
        user_id=current_user["id"],
    )

    if not success:
        return ApiResponse(
            success=False,
            message="Visualization not found",
            data=None,
        )

    return ApiResponse(
        success=True,
        message="Visualization marked as interacted",
        data={"viz_id": viz_id, "was_interacted": True},
    )
