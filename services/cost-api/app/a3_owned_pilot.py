"""Create one isolated, fixed ARKEMX fixture. No third-party rights changes."""
import hashlib
import os
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, Response
from openpyxl import Workbook
from sqlalchemy import select

from .a3_batch_review import BatchReviewRequest, SelectedRow, preview_batch_review
from .a3_review_records import SaveReviewRequest, digest, save_review
from .a3_review_store import TechnicalReviewRecord
from .m2 import DEMO_INSTITUTION, DEMO_SCOPE
from .m4 import _build_run
from .models import (
    CatalogPosition,
    CatalogSource,
    CatalogVersion,
    ImportBatch,
    MatchRun,
    Project,
    WorkItem,
)
from .technical_analysis.owned_synthetic_source import (
    CODE,
    TEXT,
    UNIT,
    VERSION,
    YEAR,
    fixture_sha256,
)

PROJECT_NAME = "A315-ARKEMX-SENTETIK-SIVA"
RECORD_TITLE = "ARKEMX sentetik siva - ilk inceleme"


def setup_owned_pilot(db, user):
    if user.role != "admin":
        raise HTTPException(403, "Admin required for fixed local fixture setup")
    projects = db.scalars(select(Project).where(Project.organization_id == user.organization_id,
        Project.name == PROJECT_NAME, Project.created_by_id == user.id)).all()
    if len(projects) > 1:
        raise ValueError("Birden fazla pilot proje var; otomatik secim yapilmadi.")
    path = None
    if not projects:
        project = Project(organization_id=user.organization_id, created_by_id=user.id, name=PROJECT_NAME)
        db.add(project); db.flush()
        source = db.scalar(select(CatalogSource).where(
            CatalogSource.organization_id == user.organization_id,
            CatalogSource.institution == DEMO_INSTITUTION,
            CatalogSource.permission_scope == DEMO_SCOPE,
            CatalogSource.license_status == "verified").order_by(CatalogSource.created_at, CatalogSource.id).limit(1))
        if source is None:
            source = CatalogSource(organization_id=user.organization_id, institution=DEMO_INSTITUTION,
                license_status="verified", permission_scope=DEMO_SCOPE, verified_by_id=user.id,
                license_evidence="Fixed ARKEMX-authored synthetic fixture; no official positions or prices")
            db.add(source); db.flush()
        version = CatalogVersion(source_id=source.id, year=YEAR, period=VERSION, sha256=fixture_sha256())
        db.add(version); db.flush()
        db.add(CatalogPosition(version_id=version.id, code=CODE, description=TEXT, unit=UNIT, price=None))
        book = Workbook(); sheet = book.active; sheet.title = "ARKEMX_SENTETIK"
        sheet.append(["description", "quantity", "unit"]); sheet.append([TEXT, 10, UNIT])
        out = BytesIO(); book.save(out); book.close(); content = out.getvalue()
        iid = str(uuid4())
        key = f"{user.organization_id}/{project.id}/{iid}.xlsx"
        path = Path(os.getenv("UPLOAD_DIR", "./data/uploads")) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream: stream.write(content)
        path.chmod(0o600)
        batch = ImportBatch(id=iid, project_id=project.id, created_by_id=user.id,
            original_filename="arkemx-owned-synthetic-plaster.xlsx", sha256=hashlib.sha256(content).hexdigest(),
            file_size=len(content), stored_key=key, sheet_name=sheet.title, row_count=1)
        db.add(batch); db.flush()
        db.add(WorkItem(import_id=batch.id, source_row=2, raw_description=TEXT, raw_quantity="10",
            raw_unit=UNIT, quantity=10, normalized_unit=UNIT, review_required=False, warnings_json="[]"))
        # Initial run supplies only this declared fixture version to the existing M4 builder.
        db.add(MatchRun(project_id=project.id, import_id=batch.id, version_id=version.id,
            created_by_id=user.id, algorithm="arkemx-owned-fixture-selection-v1", row_count=1, candidate_count=0))
        try:
            db.commit()
        except Exception:
            db.rollback(); path.unlink(missing_ok=True); raise
    else:
        project = projects[0]
    # Never overwrite existing pilot rows or reuse a real/modified catalog.
    batches = db.scalars(select(ImportBatch).where(ImportBatch.project_id == project.id)).all()
    if len(batches) != 1:
        raise ValueError("Pilot aktarimi degismis; mevcut kayitlar korunarak islem durduruldu.")
    batch = batches[0]
    rows = db.scalars(select(WorkItem).where(WorkItem.import_id == batch.id)).all()
    run = db.scalar(select(MatchRun).where(MatchRun.project_id == project.id)
        .order_by(MatchRun.created_at.desc(), MatchRun.id.desc()).limit(1))
    if run is None or len(rows) != 1 or rows[0].raw_description != TEXT or rows[0].normalized_unit != UNIT:
        raise ValueError("Pilot satiri degismis; otomatik duzeltme yapilmadi.")
    version = db.get(CatalogVersion, run.version_id)
    source = db.get(CatalogSource, version.source_id)
    positions = db.scalars(select(CatalogPosition).where(CatalogPosition.version_id == version.id)).all()
    if (source.organization_id != user.organization_id or source.institution != DEMO_INSTITUTION or
        source.permission_scope != DEMO_SCOPE or source.license_status != "verified" or
        version.period != VERSION or version.year != YEAR or version.sha256 != fixture_sha256() or len(positions) != 1 or
        positions[0].code != CODE or positions[0].description != TEXT or positions[0].unit != UNIT or positions[0].price is not None):
        raise ValueError("Sabit sentetik katalog kimligi dogrulanamadi; islem yapilmadi.")
    from .evidence_v41 import ALGORITHM
    if run.algorithm != ALGORITHM:
        _build_run(project.id, user, db, with_evidence=True)
    existing = db.scalar(select(TechnicalReviewRecord).where(TechnicalReviewRecord.project_id == project.id,
        TechnicalReviewRecord.import_id == batch.id, TechnicalReviewRecord.title == RECORD_TITLE))
    if existing is None:
        selection = SelectedRow(work_item_id=UUID(rows[0].id), candidate_code=CODE)
        preview = preview_batch_review(UUID(project.id), UUID(batch.id), BatchReviewRequest(rows=[selection]),
                                       Response(), user, db)
        saved = save_review(UUID(project.id), UUID(batch.id), SaveReviewRequest(rows=[selection],
            title=RECORD_TITLE, request_key=uuid4(), expected_report_sha256=digest(preview)), Response(), user, db)
        record_id = saved["record"]["id"]
    else:
        record_id = existing.id
    return {"project_id": project.id, "project_name": project.name, "import_id": batch.id,
            "record_id": record_id, "candidate_code": CODE, "source_kind": "synthetic_owned",
            "official_price": None, "engineering_approval": False}
