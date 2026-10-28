"""M6 - Local, read-only PDF catalog pilot preview."""

import os
import re
from pathlib import Path
from typing import Annotated

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .models import User
from .pdf_catalog_trace import link_position_evidence
from .pdf_material_evidence import link_material_evidence
from .security import current_user

router = APIRouter(
    prefix="/api/m6",
    tags=["M6 PDF Preview"],
)


@router.get("/pilot/preview")
def preview_pdf(
    request: Request,
    user: Annotated[User, Depends(current_user)],
):

    # Only permit the local pilot.
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "Yalnizca yerel erisim")
    if os.getenv("ARKEMX_ENABLE_M6_PILOT") != "1":
        raise HTTPException(403, "M6 pilot kapali")
    source = os.getenv("ARKEMX_PDF")
    if not source or not Path(source).is_file():
        raise HTTPException(404, "Yerel PDF bulunamadi")
    try:
        with pymupdf.open(source) as doc:
            page = doc[7]
            tables = page.find_tables().tables
            if len(tables) != 1:
                raise ValueError("Belirsiz tablo yapisi")
            results = link_position_evidence(
                page,
                tables[0],
                source_pdf_path=source,
                source_page=8,
                catalog_year=2026,
                catalog_period="2026-01",
            )
            if len(results) != 46:
                raise ValueError(
                    "Pilot kaynak kapsam kontrolu basarisiz"
                )
            rows = []
            for record, evidence in results:
                rows.append({
                    "code": record.code,
                    "description": record.description,
                    "unit": record.unit,
                    "price": str(record.price),
                    "source_page": evidence.source_page,
                    "source_bbox": evidence.source_bbox,
                    "source_sha256": evidence.source_sha256,
                    "validation_status": evidence.validation_status,
                })
            return {
                "page": 8,
                "total": len(rows),
                "catalog_period": "2026-01",
                "status": "read_only",
                "rows": rows,
            }
    except (ValueError, IndexError, pymupdf.FileDataError) as exc:
        raise HTTPException(
            422, "PDF kaynak dogrulamasi basarisiz"
        ) from exc


@router.get("/pilot/evidence-image/{code}")
def pilot_evidence_image(
    code: str,
    request: Request,
    user: Annotated[User, Depends(current_user)],
):
    """Render a highlighted PDF evidence crop. Read-only pilot."""
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "Yalnizca yerel erisim")
    if os.getenv("ARKEMX_ENABLE_M6_PILOT") != "1":
        raise HTTPException(403, "M6 pilot kapali")
    if not re.fullmatch(r"10\.100\.\d{4}", code):
        raise HTTPException(400, "Gecersiz poz kodu")
    source = os.getenv("ARKEMX_PDF")
    if not source or not Path(source).is_file():
        raise HTTPException(404, "Kaynak PDF bulunamadi")
    try:
        with pymupdf.open(source) as doc:
            if len(doc) < 8:
                raise ValueError("PDF sayfasi eksik")
            page = doc[7]
            tables = page.find_tables().tables
            if len(tables) != 1:
                raise ValueError("Belirsiz tablo yapisi")
            results = link_position_evidence(
                page,
                tables[0],
                source_pdf_path=source,
                source_page=8,
                catalog_year=2026,
                catalog_period="2026-01",
            )
            if len(results) != 46:
                raise ValueError("Kaynak kapsam kontrolu basarisiz")
            matches = [
                evidence
                for record, evidence in results
                if record.code == code
            ]
            if len(matches) != 1:
                raise HTTPException(404, "Poz kaniti bulunamadi")
            evidence = matches[0]
            rect = pymupdf.Rect(evidence.source_bbox)
            if rect.is_empty or not page.rect.contains(rect):
                raise ValueError("Kaynak koordinati gecersiz")
            # Show the selected row and nearby PDF context.
            clip = pymupdf.Rect(
                max(0, rect.x0 - 8),
                max(0, rect.y0 - 30),
                min(page.rect.width, rect.x1 + 8),
                min(page.rect.height, rect.y1 + 30),
            )
            # Highlight in memory only. Original PDF is never saved.
            page.draw_rect(
                rect,
                color=(0.05, 0.56, 0.22),
                fill=(0.05, 0.56, 0.22),
                fill_opacity=0.12,
                width=1.5,
                overlay=True,
            )
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(1.75, 1.75),
                clip=clip,
                alpha=False,
            )
            png = pixmap.tobytes("png")
            if len(png) > 2_000_000:
                raise HTTPException(413, "Goruntu boyutu fazla")
            return Response(
                content=png,
                media_type="image/png",
                headers={
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
    except (ValueError, IndexError, pymupdf.FileDataError) as exc:
        raise HTTPException(
            422, "PDF kaynak goruntusu dogrulanamadi"
        ) from exc


# =====================================================
# M6.0-B.11 - Material PDF catalog pilot API
# Read-only; separate from the existing labor endpoints.


# =====================================================


def _material_pilot_source(request: Request) -> Path:
    """Check local access and return the configured PDF path."""
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "Yalnizca yerel erisim")
    if os.getenv("ARKEMX_ENABLE_M6_PILOT") != "1":
        raise HTTPException(403, "M6 pilot kapali")
    source = os.getenv("ARKEMX_PDF")
    if not source or not Path(source).is_file():
        raise HTTPException(404, "Yerel PDF bulunamadi")
    return Path(source).resolve()


def _verified_material_results(doc, source_path: Path):
    """Validate the exact material pilot page and its evidence."""
    if len(doc) < 100:
        raise ValueError("Malzeme kaynak sayfasi eksik")
    page = doc[99]
    tables = page.find_tables().tables
    if len(tables) != 1:
        raise ValueError("Belirsiz malzeme tablo yapisi")
    table = tables[0]
    if table.col_count != 5:
        raise ValueError("Beklenmeyen tablo sutun sayisi")
    results = link_material_evidence(
        page,
        table,
        source_pdf_path=source_path,
        source_page=100,
        catalog_year=2026,
        catalog_period="2026-01",
    )
    codes = [record.code for record, _ in results]
    if len(results) != 16 or len(set(codes)) != 16:
        raise ValueError(
            "Malzeme kaynak kapsam kontrolu basarisiz"
        )
    return page, results


@router.get("/pilot/material/preview")
def preview_material_pdf(
    request: Request,
    user: Annotated[User, Depends(current_user)],
):
    """Return verified material records with source evidence."""
    source = _material_pilot_source(request)
    try:
        with pymupdf.open(source) as doc:
            _page, results = _verified_material_results(
                doc, source
            )
            rows = []
            for record, evidence in results:
                rows.append({
                    "code": record.code,
                    "description": record.description,
                    "unit": record.unit,
                    "purchase_place": record.purchase_place,
                    "price": str(record.price),
                    "category": "material",
                    "source_page": evidence.source_page,
                    "source_bbox": evidence.source_bbox,
                    "source_sha256": evidence.source_sha256,
                    "validation_status": evidence.validation_status,
                })
            return {
                "page": 100,
                "total": len(rows),
                "catalog_period": "2026-01",
                "status": "read_only",
                "rows": rows,
            }
    except (
        ValueError,
        IndexError,
        pymupdf.FileDataError,
    ) as exc:
        raise HTTPException(
            422,
            "Malzeme PDF kaynak dogrulamasi basarisiz",
        ) from exc


@router.get("/pilot/material/evidence-image/{code}")
def material_evidence_image(
    code: str,
    request: Request,
    user: Annotated[User, Depends(current_user)],
):
    """Render the exact material source row highlighted in green."""
    source = _material_pilot_source(request)
    if not re.fullmatch(r"10\.310\.\d{4}", code):
        raise HTTPException(400, "Gecersiz malzeme poz kodu")
    try:
        with pymupdf.open(source) as doc:
            page, results = _verified_material_results(
                doc, source
            )
            matches = [
                evidence
                for record, evidence in results
                if record.code == code
            ]
            if len(matches) == 0:
                raise HTTPException(
                    404, "Malzeme poz kaniti bulunamadi"
                )
            if len(matches) != 1:
                raise ValueError("Poz kaniti belirsiz")
            evidence = matches[0]
            rect = pymupdf.Rect(evidence.source_bbox)
            if rect.is_empty or not page.rect.contains(rect):
                raise ValueError(
                    "Kaynak koordinati gecersiz"
                )
            # Keep nearby PDF rows visible for context.
            clip = pymupdf.Rect(
                max(0, rect.x0 - 8),
                max(0, rect.y0 - 30),
                min(page.rect.width, rect.x1 + 8),
                min(page.rect.height, rect.y1 + 30),
            )
            # In-memory visual highlight only.
            # The original source PDF is never saved.
            page.draw_rect(
                rect,
                color=(0.05, 0.56, 0.22),
                fill=(0.05, 0.56, 0.22),
                fill_opacity=0.12,
                width=1.5,
                overlay=True,
            )
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(1.75, 1.75),
                clip=clip,
                alpha=False,
            )
            image_bytes = pixmap.tobytes("png")
            if len(image_bytes) > 2_000_000:
                raise HTTPException(
                    413, "Goruntu boyutu fazla"
                )
            return Response(
                content=image_bytes,
                media_type="image/png",
                headers={
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
    except (
        ValueError,
        IndexError,
        pymupdf.FileDataError,
    ) as exc:
        raise HTTPException(
            422,
            "Malzeme kaynak goruntusu dogrulanamadi",
        ) from exc
