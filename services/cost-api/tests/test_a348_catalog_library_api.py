"""A3.48.2: the PDF-only user catalog has no project, engineer or M5 writes."""
from test_a348_official_price_list import source_pdf
from test_api import register


SOURCE = "/api/a348/catalog/source"
POSITIONS = "/api/a348/catalog/positions"


def test_pdf_catalog_requires_login_and_has_empty_source(client, auth):
    assert client.get(SOURCE).status_code == 401
    assert client.post(SOURCE, files={"file": ("prices.pdf", source_pdf())}).status_code == 401
    empty = client.get(SOURCE, headers=auth)
    assert empty.status_code == 200
    assert empty.json() == {
        "present": False, "read_only": True,
        "approval_allowed": False, "cost_allowed": False,
    }
    assert client.get(POSITIONS, headers=auth).status_code == 409


def test_upload_search_page_and_selection_are_read_only(client, auth):
    uploaded = client.post(
        SOURCE, headers=auth, files={"file": ("official_2026_price_list.pdf", source_pdf())},
    )
    assert uploaded.status_code == 201, uploaded.text
    source = uploaded.json()
    assert source["read_only"] is True
    assert source["approval_allowed"] is False and source["cost_allowed"] is False
    assert source["total_records"] == 3
    assert source["audit"]["unparsed_count"] == 0
    assert source["audit"]["codes_seen"] == 3
    assert source["pdf_pages"] == 10
    assert uploaded.headers["cache-control"] == "private, no-store"

    listing = client.get(POSITIONS, headers=auth)
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert data["total"] == 3
    assert data["source_sha256"] == source["source_sha256"]
    assert data["read_only"] is True
    assert data["approval_allowed"] is False and data["cost_allowed"] is False
    assert all(row["cost_allowed"] is False for row in data["items"])
    assert listing.headers["cache-control"] == "private, no-store"

    gaz = client.get(POSITIONS, headers=auth, params={"q": "gazbeton"})
    assert gaz.status_code == 200 and gaz.json()["total"] == 1
    item = gaz.json()["items"][0]
    assert item["code"] == "15.225.1004"
    assert item["pdf_page"] == 9
    assert item["unit_price"] == "723.73"

    exact = client.get(POSITIONS, headers=auth, params={"q": "15.225.1004"})
    assert exact.json()["items"][0]["code"] == "15.225.1004"

    mechanical = client.get(POSITIONS, headers=auth, params={"kind": "mekanik"})
    assert mechanical.json()["total"] == 2
    assert mechanical.json()["items"][0]["unit_price"] is None
    assert mechanical.json()["items"][1]["installation_price"] == "6587.50"
    assert client.get(POSITIONS, headers=auth, params={"kind": "unknown"}).status_code == 422

    first = client.get(POSITIONS, headers=auth, params={"page": 1, "page_size": 1}).json()
    second = client.get(POSITIONS, headers=auth, params={"page": 2, "page_size": 1}).json()
    assert first["total"] == second["total"] == 3
    assert first["items"][0]["code"] != second["items"][0]["code"]


def test_catalog_isolation_by_organization_and_persistent_source(client):
    one = register(client, "Poz Library A", "poz-library-a@example.com")
    two = register(client, "Poz Library B", "poz-library-b@example.com")
    assert client.post(
        SOURCE, headers=one, files={"file": ("source.pdf", source_pdf())},
    ).status_code == 201
    assert client.get(SOURCE, headers=two).json()["present"] is False
    assert client.get(POSITIONS, headers=two).status_code == 409
    assert client.get(SOURCE, headers=one).json()["total_records"] == 3
    # Re-uploading the same SHA never corrupts the existing source.
    assert client.post(SOURCE, headers=one, files={"file": ("same.pdf", source_pdf())}).status_code == 201
    assert client.get(POSITIONS, headers=one).json()["total"] == 3


def test_wrong_year_rejected_without_activating_catalog(client, auth):
    rejected = client.post(
        SOURCE, headers=auth,
        files={"file": ("wrong.pdf", source_pdf(wrong_date=True))},
    )
    assert rejected.status_code == 422, rejected.text
    assert client.get(SOURCE, headers=auth).json()["present"] is False


def test_saved_pdf_catalog_has_no_project_metraj_or_price_mutations(client, auth):
    assert client.post(SOURCE, headers=auth,
                       files={"file": ("catalog.pdf", source_pdf())}).status_code == 201
    # The catalog lives in the tenant-scoped private filesystem, not the
    # project price/source tables; it cannot silently create a project.
    assert client.get("/api/projects", headers=auth).json() == []
    assert client.get("/api/catalog/sources", headers=auth).status_code in (200, 404)
