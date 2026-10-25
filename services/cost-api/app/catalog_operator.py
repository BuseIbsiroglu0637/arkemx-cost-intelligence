"""Local *operator-only* catalog rights decision.

This is intentionally not an HTTP route and not exposed to organization admins.
Run only from the system operator's protected shell after independently checking
source licence, commercial indexing/LLM rights, and proof of origin.
"""
import argparse
from hashlib import sha256
from pathlib import Path
from sqlalchemy import select
from .database import SessionLocal
from .models import CatalogImport, CatalogReviewEvent, CatalogVersion
from .m3 import SCOPE

CONFIRM = "I_VERIFIED_THE_DATASET_RIGHTS_FOR_INTERNAL_MATCHING"


def record_review(import_id: str, reviewer: str, evidence: bytes, reason: str,
                  action: str, *, confirmation: str | None = None):
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or len(reviewer) < 3 or not reason or len(reason) < 12:
        raise ValueError("Attributable reviewer and specific review reason required")
    if not evidence or len(evidence) < 30 or len(evidence) > 1024 * 1024:
        raise ValueError("Evidence must be 30 bytes to 1 MB")
    if action not in {"approve", "revoke"}:
        raise ValueError("Unsupported action")
    if action == "approve" and confirmation != CONFIRM:
        raise ValueError("Explicit independent rights confirmation required")
    with SessionLocal() as db:
        imp = db.scalar(select(CatalogImport).where(
            CatalogImport.id == import_id).with_for_update())
        if imp is None:
            raise ValueError("Catalog import ID not found")
        if action == "approve" and imp.status != "pending":
            raise ValueError("Only pending imports can be approved")
        if action == "revoke" and imp.status != "approved":
            raise ValueError("Only approved imports can be revoked")
        version = db.get(CatalogVersion, imp.version_id)
        if not version or imp.sha256 != version.sha256:
            raise ValueError("Catalog content hash mismatch")
        evidence_hash = sha256(evidence).hexdigest()
        imp.status = "approved" if action == "approve" else "rejected"
        imp.reviewed_by = reviewer
        imp.approval_scope = SCOPE if action == "approve" else None
        imp.approval_evidence = (
            f"sha256:{evidence_hash} | {reason[:400]}"
            if action == "approve" else None
        )
        from datetime import datetime, timezone
        imp.reviewed_at = datetime.now(timezone.utc)
        db.add(CatalogReviewEvent(
            catalog_import_id=imp.id, action=action, reviewer=reviewer,
            scope=SCOPE, evidence_sha256=evidence_hash, catalog_sha256=imp.sha256,
            reason=reason))
        db.commit()
        return {"import_id": imp.id, "status": imp.status, "evidence_sha256": evidence_hash}


def main():
    parser = argparse.ArgumentParser(description="M3 operator rights-gate CLI")
    parser.add_argument("action", choices=["approve", "revoke"])
    parser.add_argument("--import-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--evidence-file", required=True,
                        help="Local rights proof file. Never committed/uploaded by app.")
    parser.add_argument("--reason", required=True,
                        help="Cite licensor, date, granted scope or revocation basis.")
    parser.add_argument("--confirm-rights", default="")
    args = parser.parse_args()
    path = Path(args.evidence_file).resolve()
    if not path.is_file():
        parser.error("Evidence file does not exist")
    try:
        result = record_review(
            args.import_id, args.reviewer, path.read_bytes(),
            args.reason, args.action, confirmation=args.confirm_rights)
    except ValueError as exc:
        parser.error(str(exc))
    print(result)


if __name__ == "__main__":
    main()
