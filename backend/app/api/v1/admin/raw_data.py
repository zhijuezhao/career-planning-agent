from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.job import JobRawData
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import JobRawDataResponse, JobRawDataListResponse

router = APIRouter()


@router.get("", response_model=JobRawDataListResponse)
async def list_raw_data(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    industry: str | None = None,
    city: str | None = None,
    is_active: bool | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List raw job data with optional filtering."""
    query = select(JobRawData)
    count_query = select(func.count()).select_from(JobRawData)

    if industry:
        query = query.where(JobRawData.industry == industry)
        count_query = count_query.where(JobRawData.industry == industry)
    if city:
        query = query.where(JobRawData.city == city)
        count_query = count_query.where(JobRawData.city == city)
    if is_active is not None:
        query = query.where(JobRawData.is_active == is_active)
        count_query = count_query.where(JobRawData.is_active == is_active)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(JobRawData.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return JobRawDataListResponse(
        total=total,
        items=[JobRawDataResponse.model_validate(item) for item in items],
    )


@router.get("/{data_id}", response_model=JobRawDataResponse)
async def get_raw_data(
    data_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single raw data entry by ID."""
    data = await db.get(JobRawData, data_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Raw data not found")
    return data


@router.delete("/{data_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_raw_data(
    data_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single raw data entry."""
    data = await db.get(JobRawData, data_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Raw data not found")

    await db.delete(data)
    await db.flush()


@router.post("/batch-delete", status_code=status.HTTP_204_NO_CONTENT)
async def batch_delete_raw_data(
    data_ids: list[int],
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Batch delete raw data entries."""
    if not data_ids:
        raise HTTPException(status_code=400, detail="No data IDs provided")

    for data_id in data_ids:
        data = await db.get(JobRawData, data_id)
        if data:
            await db.delete(data)

    await db.flush()
