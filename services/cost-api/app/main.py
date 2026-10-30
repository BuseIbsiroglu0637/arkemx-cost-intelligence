"""ARKEMX Cost Intelligence M1 API: tenant-scoped projects and metraj import."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from typing import Annotated
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import Organization, User, Project, ImportBatch, WorkItem, CatalogSource
from .security import hash_password, verify_password, create_token, current_user, key
from .excel import read_metraj, safe_name, ExcelValidationError, MAX_FILE_BYTES, open_sheet, guess_map


# Refuse production startup when a proper JWT signing secret is not configured.
if os.getenv("ENVIRONMENT", "development") != "development":
    key()

app = FastAPI(title="ARKEMX Cost Intelligence API", version="0.1.0")
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in origins],
                   allow_credentials=False, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"])


class RegisterRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ProjectRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class SourceRequest(BaseModel):
    institution: str = Field(min_length=2, max_length=200)
    source_url: str | None = None
    license_evidence: str | None = None
    permission_scope: str | None = None


class VerifySourceRequest(BaseModel):
    license_evidence: str = Field(min_length=10)
    permission_scope: str = Field(min_length=5)


def permitted_project(db: Session, user: User, project_id: str) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id,
                                              Project.organization_id == user.organization_id))
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def source_view(source: CatalogSource) -> dict:
    return {"id": source.id, "institution": source.institution, "source_url": source.source_url,
            "license_status": source.license_status, "license_evidence": source.license_evidence,
            "permission_scope": source.permission_scope, "verified_at": source.verified_at}


@app.get("/api/health")
def health():
    return {"status": "ok", "product": "ARKEMX Cost Intelligence", "version": "0.1.0"}


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    org = Organization(name=payload.organization_name.strip())
    db.add(org)
    db.flush()
    user = User(organization_id=org.id, email=email, password_hash=hash_password(payload.password), role="admin")
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered") from None
    return {"access_token": create_token(user), "token_type": "bearer", "organization_id": org.id}


@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": create_token(user), "token_type": "bearer", "organization_id": user.organization_id}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "organization_id": user.organization_id, "email": user.email, "role": user.role}


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = Project(name=payload.name.strip(), organization_id=user.organization_id, created_by_id=user.id)
    db.add(project)
    db.commit()
    return {"id": project.id, "name": project.name, "created_at": project.created_at}


from .project_deletion import router as project_deletion_router
app.include_router(project_deletion_router)


@app.get("/api/projects")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).where(Project.organization_id == user.organization_id)
                          .order_by(Project.created_at.desc())).all()
    return [{"id": p.id, "name": p.name, "created_at": p.created_at} for p in projects]


async def load_upload(file: UploadFile) -> bytes:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(415, "Only .xlsx files are supported")
    # Stream with hard cap, never trust Content-Length.
    content = await file.read(MAX_FILE_BYTES + 1)
    await file.close()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, "Maximum file size 10MB")
    return content


def parsed(content, sheet, description_column, quantity_column, unit_column, header_row=1):
    mapping = {"description": description_column, "quantity": quantity_column, "unit": unit_column}
    try:
        return read_metraj(content, sheet=sheet, columns=mapping, header_row=header_row)
    except ExcelValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/imports/inspect")
async def inspect(file: Annotated[UploadFile, File()],
                  sheet: Annotated[str | None, Form()] = None,
                  header_row: Annotated[int, Form(ge=1, le=30)] = 1,
                  user: User = Depends(current_user)):
    content = await load_upload(file)
    try:
        book, tab = open_sheet(content, sheet)
        headers = [str(cell.value).strip() if cell.value is not None else f"Column {idx+1}"
                   for idx, cell in enumerate(next(tab.iter_rows(min_row=header_row), ()))]
        if len(set(headers)) != len(headers):
            raise ExcelValidationError("Duplicate headers: rename columns in Excel")
        return {"headers": headers, "mapping": guess_map(headers), "sheets": book.sheetnames, "selected_sheet": tab.title, "header_row": header_row}
    except ExcelValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        if "book" in locals():
            book.close()


@app.post("/api/imports/preview")
async def preview(file: Annotated[UploadFile, File()],
                  sheet: Annotated[str | None, Form()] = None,
                  description_column: Annotated[str | None, Form()] = None,
                  quantity_column: Annotated[str | None, Form()] = None,
                  unit_column: Annotated[str | None, Form()] = None,
                  header_row: Annotated[int, Form(ge=1, le=30)] = 1,
                  user: User = Depends(current_user)):
    content = await load_upload(file)
    result = parsed(content, sheet, description_column, quantity_column, unit_column, header_row)
    return {**{k: v for k, v in result.items() if k != "items"}, "items": result["items"][:30]}


@app.post("/api/projects/{project_id}/imports", status_code=201)
async def import_metraj(project_id: str, file: Annotated[UploadFile, File()],
                        sheet: Annotated[str | None, Form()] = None,
                        description_column: Annotated[str | None, Form()] = None,
                        quantity_column: Annotated[str | None, Form()] = None,
                        unit_column: Annotated[str | None, Form()] = None,
                        header_row: Annotated[int, Form(ge=1, le=30)] = 1,
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    permitted_project(db, user, project_id)
    filename = safe_name(file.filename or "metraj.xlsx")
    content = await load_upload(file)
    result = parsed(content, sheet, description_column, quantity_column, unit_column, header_row)
    batch_id = str(uuid4())
    key = f"{user.organization_id}/{project_id}/{batch_id}.xlsx"
    storage_root = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
    path = storage_root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    # No file access endpoint; tenant path constructed solely from DB-controlled UUIDs.
    # Production requires encrypted at-rest volume/object storage.
    try:
        with path.open("xb") as output:
            output.write(content)
        path.chmod(0o600)
        batch = ImportBatch(id=batch_id, project_id=project_id, created_by_id=user.id,
                            original_filename=filename, sha256=hashlib.sha256(content).hexdigest(),
                            file_size=len(content), stored_key=key, sheet_name=result["sheet"],
                            row_count=result["row_count"])
        db.add(batch)
        for item in result["items"]:
            db.add(WorkItem(import_id=batch_id, source_row=item["source_row"],
                            raw_description=item["description"], raw_quantity=item["raw_quantity"],
                            raw_unit=item["raw_unit"], quantity=item["quantity"],
                            normalized_unit=item["unit"], review_required=item["review_required"],
                            warnings_json=json.dumps(item["issues"], ensure_ascii=False)))
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return {"id": batch_id, "row_count": result["row_count"],
            "review_count": result["review_count"], "sha256": batch.sha256}


@app.get("/api/projects/{project_id}/imports")
def list_imports(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    permitted_project(db, user, project_id)
    batches = db.scalars(select(ImportBatch).where(ImportBatch.project_id == project_id)
                         .order_by(ImportBatch.created_at.desc())).all()
    return [{"id": b.id, "filename": b.original_filename, "sha256": b.sha256,
             "row_count": b.row_count, "sheet": b.sheet_name, "created_at": b.created_at} for b in batches]


@app.get("/api/projects/{project_id}/items")
def list_items(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    permitted_project(db, user, project_id)
    items = db.scalars(select(WorkItem).join(ImportBatch, WorkItem.import_id == ImportBatch.id)
                       .where(ImportBatch.project_id == project_id)
                       .order_by(ImportBatch.created_at.desc(), WorkItem.source_row.asc())
                       .limit(2000)).all()
    return [{"id": item.id, "source_row": item.source_row, "description": item.raw_description,
             "quantity": str(item.quantity) if item.quantity is not None else None,
             "raw_quantity": item.raw_quantity, "raw_unit": item.raw_unit,
             "unit": item.normalized_unit, "review_required": item.review_required,
             "issues": json.loads(item.warnings_json)} for item in items]


@app.post("/api/catalog/sources", status_code=201)
def create_source(payload: SourceRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = CatalogSource(organization_id=user.organization_id,
                           institution=payload.institution, source_url=payload.source_url,
                           license_evidence=payload.license_evidence,
                           permission_scope=payload.permission_scope, license_status="pending")
    db.add(source)
    db.commit()
    return source_view(source)


@app.get("/api/catalog/sources")
def list_sources(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sources = db.scalars(select(CatalogSource).where(CatalogSource.organization_id == user.organization_id)).all()
    return [source_view(s) for s in sources]


@app.post("/api/catalog/sources/{source_id}/verify")
def verify_source(source_id: str, payload: VerifySourceRequest,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Admin required")
    source = db.scalar(select(CatalogSource).where(CatalogSource.id == source_id,
                                                  CatalogSource.organization_id == user.organization_id))
    if not source:
        raise HTTPException(404, "Source not found")
    source.license_evidence = payload.license_evidence.strip()
    source.permission_scope = payload.permission_scope.strip()
    source.license_status = "verified"
    source.verified_by_id = user.id
    source.verified_at = datetime.now(timezone.utc)
    db.commit()
    return source_view(source)


# M2 routes are separated to keep M1 Excel import unchanged.
from .m2 import router as m2_router
app.include_router(m2_router)

# Append-only metraj revision routes (M2.1)
from .m21 import router as m21_router
app.include_router(m21_router)

# M3 rights-gated external catalog routes
from .m3 import router as m3_router
app.include_router(m3_router)

# M4 explainable deterministic technical comparison routes
from .m4 import router as m4_router
app.include_router(m4_router)

# M4.1 versioned source-attributed technical evidence
from .m41 import router as m41_router
app.include_router(m41_router)

# M4.2 paginated engineer review queue and on-demand evidence/history
from .m42 import router as m42_router
app.include_router(m42_router)

# M4.3 durable local batch queue
from .m43 import router as m43_router
app.include_router(m43_router)


# M5 locally priced draft cost snapshots (not official tariffs or final offers)
from .m5 import router as m5_router
app.include_router(m5_router)

# M5.1 read-only saved-draft comparisons and non-persistent revision simulations
from .m51 import router as m51_router
app.include_router(m51_router)

# M5.2 Excel-vs-Excel review and explicit append-only revised import
from .m52 import router as m52_router
app.include_router(m52_router)

# M5.2.1 safety controls: cancel queued only, exclusion audit and source selection
from .m521 import router as m521_router
app.include_router(m521_router)

from .m6_preview import router as m6_preview_router
app.include_router(m6_preview_router)

# A3.1 technical comparison preview
from .a3_technical_review import router as a3_technical_review_router
app.include_router(a3_technical_review_router)

from .a3_cost_scenario import router as a3_cost_scenario_router
app.include_router(a3_cost_scenario_router)

# A3.9.2 selected metraj rows, read-only technical preview
from .a3_batch_review import router as a3_batch_review_router
app.include_router(a3_batch_review_router)

# Explicit saved previews; separate from engineering decisions and costing.
from .a3_review_records import router as a3_review_records_router
app.include_router(a3_review_records_router)

from .a3_review_assessments import router as a3_review_assessments_router
app.include_router(a3_review_assessments_router)

from .a3_m4_bridge import router as a3_m4_bridge_router
app.include_router(a3_m4_bridge_router)

# A3.17 read-only authorized catalog suggestions; no approval or pricing.
from .a317_suggestions import router as a317_suggestions_router
app.include_router(a317_suggestions_router)

# A3.18 direct local analysis-PDF source (no synthetic catalog or automatic approval).
from .a318_pdf_api import router as a318_pdf_router
app.include_router(a318_pdf_router)

# A3.26 project technical specification evidence (local-only, not engineering approval).
from .a326_project_evidence import router as a326_project_evidence_router
app.include_router(a326_project_evidence_router)

# A3.27.1 read-only engineer handoff queue; never issues approvals.
from .a327_engineer_handoff import router as a327_engineer_handoff_router
app.include_router(a327_engineer_handoff_router)

# A3.27.2 append-only review handoff notes; no certified engineer approval.
from .a327_decisions import router as a327_decisions_router
app.include_router(a327_decisions_router)

