
"""A3.7 - Authenticated, read-only cost scenario API.

The alternative price is a constrained pilot fixture.
No approval, database writes or cost estimate creation.
"""

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from .models import User
from .security import current_user
from .technical_analysis.cost_scenario import (
    calculate_300kg_scenario,
)
from .technical_analysis.pdf_analysis_source import read_analysis

router = APIRouter(
    prefix="/api/a3",
    tags=["A3 Cost Scenario"],
)


class CostScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alternative_resource_code: Literal["19.100.2506"]


@router.post("/cost-scenario")
def preview_cost_scenario(
    payload: CostScenarioRequest,
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

        scenario = calculate_300kg_scenario(
            analysis,
            alternative_code=payload.alternative_resource_code,
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Scenario source could not be verified",
            headers={"Cache-Control": "private, no-store"},
        ) from exc

    if (
        scenario.get("approval_allowed") is not False
        or scenario.get("read_only") is not True
    ):
        raise HTTPException(
            status_code=500,
            detail="Unsafe scenario result",
            headers={"Cache-Control": "private, no-store"},
        )

    response.headers["Cache-Control"] = "private, no-store"

    return {
        "schema": "arkemx.cost_scenario_preview.v1",
        "read_only": True,
        "approval_allowed": False,
        "scenario": scenario,
    }
