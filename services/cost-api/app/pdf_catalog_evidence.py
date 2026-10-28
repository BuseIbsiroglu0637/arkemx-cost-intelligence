
"""M6.0-A.29 - PDF position source evidence.

Stores verifiable source metadata.
Does not approve positions or import catalogs.
"""

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.pdf_catalog_parser import ParsedRow


def sha256_file(path: str | Path) -> str:
    """Calculate SHA-256 without loading the whole PDF."""
    digest = hashlib.sha256()

    with open(path, "rb") as source:
        for chunk in iter(
            lambda: source.read(1024 * 1024), b""
        ):
            digest.update(chunk)

    return digest.hexdigest()


@dataclass(frozen=True)
class PositionEvidence:
    code: str
    source_page: int
    source_bbox: tuple[float, float, float, float]
    page_size: tuple[float, float]
    source_sha256: str
    catalog_year: int
    catalog_period: str
    record_type: str
    validation_status: str = "needs_review"

    def __post_init__(self):
        if not self.code.strip():
            raise ValueError("Poz kodu eksik")

        if self.source_page < 1:
            raise ValueError("Kaynak sayfasi gecersiz")

        if not re.fullmatch(
            r"[0-9a-fA-F]{64}", self.source_sha256
        ):
            raise ValueError("SHA-256 gecersiz")

        if self.record_type not in {"rayic", "imalat"}:
            raise ValueError("Kayit turu gecersiz")

        if self.validation_status not in {
            "candidate", "needs_review"
        }:
            raise ValueError("Dogrulama durumu gecersiz")

        period_match = re.fullmatch(
            r"(\d{4})-(0[1-9]|1[0-2])",
            self.catalog_period,
        )

        if (
            not period_match
            or int(period_match.group(1))
            != self.catalog_year
        ):
            raise ValueError("Katalog donemi gecersiz")

        if len(self.source_bbox) != 4:
            raise ValueError("Koordinat sayisi gecersiz")

        if len(self.page_size) != 2:
            raise ValueError("Sayfa boyutu gecersiz")

        x0, y0, x1, y1 = self.source_bbox
        width, height = self.page_size

        if not all(
            math.isfinite(value)
            for value in (
                x0, y0, x1, y1, width, height
            )
        ):
            raise ValueError("Koordinatlar sonlu olmali")

        if not (
            width > 0
            and height > 0
            and 0 <= x0 < x1 <= width
            and 0 <= y0 < y1 <= height
        ):
            raise ValueError("Koordinatlar sayfa disinda")


def create_position_evidence(
    record: ParsedRow,
    *,
    source_bbox: tuple[float, float, float, float],
    page_size: tuple[float, float],
    source_sha256: str,
    catalog_year: int,
    catalog_period: str,
    record_type: str,
) -> PositionEvidence:
    """Build a reviewable evidence record.

    Coordinates must be obtained from the PDF,
    not inferred from the position code.
    """
    return PositionEvidence(
        code=record.code,
        source_page=record.source_page,
        source_bbox=source_bbox,
        page_size=page_size,
        source_sha256=source_sha256,
        catalog_year=catalog_year,
        catalog_period=catalog_period,
        record_type=record_type,
    )
