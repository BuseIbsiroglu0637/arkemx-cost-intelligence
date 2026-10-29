"""A3.1 - Authenticated, non-persistent technical comparison preview."""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import User
from .security import current_user
from .technical_analysis.comparator import compare_layers
from .technical_analysis.pdf_analysis_source import read_analysis

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
class PdfTechnicalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metraj_description: str = Field(
        min_length=3,
        max_length=5000,
    )

    @field_validator("metraj_description")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "Description must contain non-whitespace text"
            )
        return value


@router.post("/compare-pdf")

def preview_pdf_technical_review(
    payload: PdfTechnicalReviewRequest,
    response: Response,
    _user: Annotated[User, Depends(current_user)],
):
    pdf_path = os.environ.get("ARKEMX_ANALYSIS_PDF")

    if not pdf_path:
        raise HTTPException(
            status_code=503,
            detail="PDF analysis source is not configured",
            headers={"Cache-Control": "private, no-store"},
        )

    try:
        analysis = read_analysis(pdf_path)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF analysis source could not be verified",
            headers={"Cache-Control": "private, no-store"},
        ) from exc

    catalog_description = analysis["technical_description"]["quote"]

    try:
        comparison = compare_layers(
            payload.metraj_description,
            catalog_description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Source evidence could not be validated",
            headers={"Cache-Control": "private, no-store"},
        ) from exc

    if comparison.get("approval_allowed") is not False:
        raise HTTPException(
            status_code=500,
            detail="Preview cannot authorize engineering approval",
            headers={"Cache-Control": "private, no-store"},
        )

    response.headers["Cache-Control"] = "private, no-store"

    return {
        "schema": "arkemx.pdf_technical_review_preview.v1",
        "read_only": True,
        "approval_allowed": False,
        "sources": {
            "metraj": payload.metraj_description,
            "catalog": catalog_description,
        },
        "catalog_analysis": analysis,
        "comparison": comparison,
    }