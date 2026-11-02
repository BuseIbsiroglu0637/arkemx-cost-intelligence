"""Durable private catalog storage independent of the code checkout and upload dir.

Legacy A3.48 sources were stored inside UPLOAD_DIR, often in a per-release
test runtime folder. After a single verified migration, catalogs live in
ARKEMX_CATALOG_HOME or the OS user's stable application data directory.

Migration is copy-only and does NOT delete or modify legacy source files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

CATALOG_DIRS = {
    "price-list": "_a348_official_price_library",
    "analysis": "_a348_official_analysis_library",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def _durable_home() -> Path:
    explicit = os.environ.get("ARKEMX_CATALOG_HOME")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ARKEMX" / "catalogs"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "ARKEMX" / "catalogs"


def _no_symlinks(path: Path) -> bool:
    path = path.absolute()
    return not any(part.is_symlink() for part in (path, *path.parents))


def _verify_active_source(root: Path, kind: str) -> None:
    """Check source fingerprints and refuse any link traversal before copying."""
    if not _no_symlinks(root):
        raise ValueError("Unsafe legacy catalog path")
    pointer = root / "current.json"
    info = json.loads(pointer.read_text(encoding="utf-8"))
    sha = info["source_sha256"]
    index_sha = info["index_sha256"]
    if not SHA256_RE.fullmatch(sha) or not SHA256_RE.fullmatch(index_sha):
        raise ValueError("Invalid catalog source hash")
    index_filename = info.get("index_file", "analysis.json") if kind == "analysis" else "catalog.json"
    if index_filename not in ({"analysis.json", "analysis-a3484.json"} if kind == "analysis" else {"catalog.json"}):
        raise ValueError("Unexpected catalog index filename")
    version = root / sha
    pdf = version / "source.pdf"
    idx = version / index_filename
    if not all(_no_symlinks(f) and f.is_file() for f in (pdf, idx)):
        raise ValueError("Catalog source or index unavailable")
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != sha:
        raise ValueError("Source PDF fingerprint mismatch")
    index_bytes = idx.read_bytes()
    if hashlib.sha256(index_bytes).hexdigest() != index_sha:
        raise ValueError("Source index fingerprint mismatch")
    document = json.loads(index_bytes)
    if (document.get("source_sha256") != sha or document.get("read_only") is not True
            or document.get("approval_allowed") is not False
            or document.get("cost_allowed") is not False):
        raise ValueError("Catalog index has unexpected status")
    expected_schema = (
        "arkemx.a348.official_price_catalog.v1"
        if kind == "price-list" else "arkemx.a348.analysis_catalog.v1"
    )
    if document.get("schema") != expected_schema:
        raise ValueError("Unrecognized catalog schema")


def catalog_root(organization_id: str, kind: str) -> Path:
    """Get stable per-organization catalog path; migrate once if necessary.

    Existing catalogs in the old UPLOAD_DIR are copied exactly once. When the
    stable root already exists, it is authoritative and never overwritten by
    an obsolete copy. Missing/corrupt legacy data fails visibly, not silently.
    """
    if kind not in CATALOG_DIRS:
        raise ValueError("Unknown catalog type")
    if not SAFE_ID_RE.fullmatch(organization_id):
        raise ValueError("Invalid organization identifier")
    root = _durable_home() / organization_id / kind
    if not _no_symlinks(root):
        raise ValueError("Unsafe persistent catalog path")
    if root.exists():
        if not root.is_dir():
            raise ValueError("Persistent catalog path is not a directory")
        return root

    uploads = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
    old_root = uploads / CATALOG_DIRS[kind] / organization_id
    if not (old_root / "current.json").is_file():
        return root
    _verify_active_source(old_root, kind)

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.parent / (".catalog-copy-" + uuid4().hex)
    if not _no_symlinks(staging):
        raise ValueError("Unsafe catalog staging directory")
    try:
        # Require all copied historical PDF/index files to be regular files.
        # shutil.copytree with symlinks=False would silently follow a symlink,
        # so validate the entire source tree first.
        for item in old_root.rglob("*"):
            if item.is_symlink():
                raise ValueError("Legacy catalog includes unsafe symlink")
        shutil.copytree(old_root, staging)
        _verify_active_source(staging, kind)
        if not root.exists():
            try:
                staging.rename(root)
            except OSError:
                if not root.is_dir():
                    raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return root
