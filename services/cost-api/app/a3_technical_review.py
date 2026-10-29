"""A3.1 - Authenticated, non-persistent technical comparison preview."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import User
from .security import current_user
from .technical_analysis.comparator import compare_layers

router = APIRouter(
    prefix="/api/a3",
    tags=["A3 Technical Review"],
)


class TechnicalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metraj_description: str = Field(
        min_length=3,
        max_length=5000,
    )
    catalog_description: str = Field(
        min_length=3,
        max_length=5000,
    )

    @field_validator(
        "metraj_description",
        "catalog_description",
    )
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "Description must contain non-whitespace text"
            )

        # Preserve original text and evidence offsets.
        return value


@router.post("/compare")
def preview_technical_review(
    payload: TechnicalReviewRequest,
    response: Response,
    _user: Annotated[User, Depends(current_user)],
):
    try:
        comparison = compare_layers(
            payload.metraj_description,
            payload.catalog_description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Source evidence could not be validated",
        ) from exc

    if comparison.get("approval_allowed") is not False:
        raise HTTPException(
            status_code=500,
            detail="Preview cannot authorize engineering approval",
        )

    response.headers["Cache-Control"] = "private, no-store"

    return {
        "schema": "arkemx.technical_review_preview.v1",
        "read_only": True,
        "sources": {
            "metraj": payload.metraj_description,
            "catalog": payload.catalog_description,
        },
        "comparison": comparison,
    }
