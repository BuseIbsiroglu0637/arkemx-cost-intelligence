"""Shared fail-closed policy for explicitly excluded Excel sources.

No implicit fallback to older imports: old technical decisions stay historical.
"""
from fastapi import HTTPException
from .models import MetrajImportExclusion

def guard_source(db, import_id):
    if import_id and db.get(MetrajImportExclusion, import_id):
        raise HTTPException(409, "The current metraj source has been excluded. Upload a clean new Excel; previous technical approvals are not reactivated.")

def source_excluded(db, import_id):
    return bool(import_id and db.get(MetrajImportExclusion, import_id))
