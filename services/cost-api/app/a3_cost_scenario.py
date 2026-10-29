
"""A3.8.4 - PDF-backed, read-only cost scenario API."""

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from .models import User
from .security import current_user
from .technical_analysis.alternative_mortar_source import (
    read_alternative_mortar,
)
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


def unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=detail,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/cost-scenario")
def preview_cost_scenario(
    payload: CostScenarioRequest,
    response: Response,
    _user: Annotated[User, Depends(current_user)],
):
    original_path = os.environ.get("ARKEMX_ANALYSIS_PDF")
    alternative_path = os.environ.get("ARKEMX_ALT_PDF")

    if not original_path or not alternative_path:
        raise unavailable("Required PDF source is not configured")

    try:
        original = read_analysis(original_path)
        alternative = read_alternative_mortar(alternative_path)

        if (
            alternative["position_code"]
            != payload.alternative_resource_code
            or alternative["unit"] != "m³"
            or alternative["read_only"] is not True
            or alternative["approval_allowed"] is not False
        ):
            raise ValueError("Unsafe alternative source")

        scenario = calculate_300kg_scenario(
            original,
            alternative_code=alternative["position_code"],
            alternative_unit=alternative["unit"],
            alternative_unit_price=alternative["unit_price_tl"],
        )

        if (
            scenario.get("read_only") is not True
            or scenario.get("approval_allowed") is not False
        ):
            raise ValueError("Unsafe scenario result")

    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        raise unavailable(
            "Scenario PDF sources could not be verified"
        ) from exc

    # Mark the price source verified only after both pinned
    # PDF readers and the scenario calculation succeeded.
    scenario["alternative_price_verification"] = (
        "verified_source_document"
    )

    scenario["alternative_price_source"] = {
        "position_code": alternative["position_code"],
        "description": alternative["description"],
        "unit": alternative["unit"],
        "unit_price_tl": alternative["unit_price_tl"],
        "source": alternative["source"],
        "evidence": alternative["evidence"],
    }

    response.headers["Cache-Control"] = "private, no-store"

    return {
        "schema": "arkemx.cost_scenario_preview.v1",
        "read_only": True,
        "approval_allowed": False,
        "scenario": scenario,
    }
