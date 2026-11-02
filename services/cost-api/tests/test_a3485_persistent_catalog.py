"""Permanent 2026 catalog survives new checkout and upload-path changes."""
import json
import shutil

import pytest

from app.a348_persistent_catalog import catalog_root
from test_a348_official_price_list import source_pdf
from test_a348_analysis_library_api import fake_analysis_pdf, sample_position


def _org_id(client, auth):
    user = client.get("/api/me", headers=auth)
    assert user.status_code == 200, user.text
    return user.json()["organization_id"]


def test_catalogs_stay_available_after_upload_root_changes(client, auth, monkeypatch, tmp_path):
    from app import a348_analysis_library_api as analysis
    monkeypatch.setattr(analysis, "read_positions", lambda raw: [sample_position()])
    price = client.post("/api/a348/catalog/source", headers=auth,
                        files={"file": ("price.pdf", source_pdf())})
    a = client.post("/api/a348/catalog/analysis/source", headers=auth,
                    files={"file": ("analysis.pdf", fake_analysis_pdf())})
    assert price.status_code == 201, price.text
    assert a.status_code == 201, a.text

    year = price.json()["edition_date"].split(".")[-1]
    assert year == "2026"
    org = _org_id(client, auth)
    for kind in ("price-list", "analysis"):
        folder = catalog_root(org, kind)
        assert (folder / "current.json").is_file()
        assert (folder / json.loads((folder / "current.json").read_text())["source_sha256"] / "source.pdf").is_file()

    # Simulates opening ARKEMX from a different worktree/release.
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "next-release" / "uploads"))
    assert client.get("/api/a348/catalog/source", headers=auth).json()["total_records"] == 3
    assert client.get("/api/a348/catalog/analysis/source", headers=auth).json()["position_count"] == 1
    linkage = client.get("/api/a348/catalog/linkage", headers=auth).json()
    assert linkage["linked_count"] == 1
    assert linkage["catalog_total"] == 3


def test_old_catalogs_are_verified_and_copied_only_once(client, auth, monkeypatch, tmp_path):
    org = _org_id(client, auth)
    prices = client.post("/api/a348/catalog/source", headers=auth,
                         files={"file": ("price.pdf", source_pdf())})
    assert prices.status_code == 201, prices.text
    stable = catalog_root(org, "price-list")
    legacy = tmp_path / "uploads" / "_a348_official_price_library" / org
    legacy.parent.mkdir(parents=True)
    shutil.copytree(stable, legacy)
    stable_source = next(stable.glob("*/source.pdf"))
    source_original = stable_source.read_bytes()

    shutil.rmtree(stable)
    recovered = client.get("/api/a348/catalog/source", headers=auth)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["total_records"] == 3
    assert stable_source.read_bytes() == source_original
    assert next(legacy.glob("*/source.pdf")).read_bytes() == source_original

    # Migrated data wins over any old upload paths on subsequent releases.
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "other-upload"))
    assert client.get("/api/a348/catalog/source", headers=auth).json()["total_records"] == 3
    assert stable_source.read_bytes() == source_original


def test_corrupt_legacy_catalog_is_never_silently_accepted(client, auth, monkeypatch, tmp_path):
    org = _org_id(client, auth)
    uploaded = client.post("/api/a348/catalog/source", headers=auth,
                           files={"file": ("price.pdf", source_pdf())})
    assert uploaded.status_code == 201
    stable = catalog_root(org, "price-list")
    legacy = tmp_path / "uploads" / "_a348_official_price_library" / org
    legacy.parent.mkdir(parents=True)
    shutil.copytree(stable, legacy)
    shutil.rmtree(stable)
    pdf = next(legacy.glob("*/source.pdf"))
    pdf.write_bytes(b"corrupted PDF")
    response = client.get("/api/a348/catalog/source", headers=auth)
    assert response.status_code == 409
    assert not stable.exists()


def test_analysis_migrates_from_old_runtime_with_index_version(client, auth, monkeypatch, tmp_path):
    from app import a348_analysis_library_api as analysis
    monkeypatch.setattr(analysis, "read_positions", lambda raw: [sample_position()])
    org = _org_id(client, auth)
    uploaded = client.post("/api/a348/catalog/analysis/source", headers=auth,
                           files={"file": ("cilt1.pdf", fake_analysis_pdf())})
    assert uploaded.status_code == 201
    stable = catalog_root(org, "analysis")
    legacy = tmp_path / "uploads" / "_a348_official_analysis_library" / org
    legacy.parent.mkdir(parents=True)
    shutil.copytree(stable, legacy)
    shutil.rmtree(stable)
    result = client.get("/api/a348/catalog/analysis/source", headers=auth)
    assert result.status_code == 200, result.text
    assert result.json()["position_count"] == 1
    assert catalog_root(org, "analysis").is_dir()
