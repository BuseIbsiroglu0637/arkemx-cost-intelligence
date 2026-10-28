
"""M6.0-C.4 - Resumable, read-only PDF catalog analysis."""

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import pymupdf

from .pdf_table_classifier import classify_table, find_table_overlaps

SCHEMA_VERSION = "m6-d4-v2"
DEFAULT_REPORT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "m6_catalog_report_d4.json"
)


def source_fingerprint(path: Path, page_count: int) -> dict:
    """Identify the PDF without modifying its contents."""
    before = path.stat()
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)

    after = path.stat()

    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise RuntimeError("PDF changed while hashing")

    return {
        "path": str(path.resolve()),
        "filename": path.name,
        "size_bytes": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "sha256": digest.hexdigest(),
        "page_count": page_count,
    }


def atomic_write(path: Path, payload: dict) -> None:
    """Write a complete JSON file before replacing the destination."""
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    os.replace(temporary, path)


def analyze_page(page, page_number: int) -> dict:
    """Classify every detected table on one PDF page."""
    tables = page.find_tables().tables
    profiles = [classify_table(table) for table in tables]

    records = []

    for index, profile in enumerate(profiles, 1):
        records.append({
            "table_index": index,
            "column_count": profile.column_count,
            "row_count": profile.row_count,
            "family": profile.family,
            "candidate_codes": list(profile.codes),
            "duplicate_codes": list(profile.duplicate_codes),
            "malformed_code_count": len(profile.malformed_codes),
            "malformed_examples": list(
                profile.malformed_codes[:10]
            ),
        })

    overlaps = []

    for first, second, codes in find_table_overlaps(profiles):
        overlaps.append({
            "first_table": first,
            "second_table": second,
            "shared_codes": list(codes),
        })

    return {
        "page_number": page_number,
        "table_count": len(records),
        "tables": records,
        "overlaps": overlaps,
        "error": None,
    }


def summarize_pages(pages: list[dict]) -> dict:
    """Aggregate observations, not approved catalog records."""
    column_counts = Counter()
    family_counts = Counter()
    code_counts = Counter()

    table_total = 0
    pages_without_tables = 0
    error_pages = 0
    overlapping_pairs = 0
    pages_with_overlaps = 0

    for page in pages:
        if page["error"] is not None:
            error_pages += 1
            continue

        tables = page["tables"]
        table_total += len(tables)

        if not tables:
            pages_without_tables += 1

        for table in tables:
            column_counts[str(table["column_count"])] += 1
            family_counts[table["family"]] += 1
            code_counts.update(table["candidate_codes"])

        if page["overlaps"]:
            pages_with_overlaps += 1
            overlapping_pairs += len(page["overlaps"])

    repeated = {
        code: count
        for code, count in code_counts.items()
        if count > 1
    }

    return {
        "scanned_pages": len(pages),
        "tables_total": table_total,
        "pages_without_tables": pages_without_tables,
        "scan_error_pages": error_pages,
        "tables_by_columns": dict(sorted(column_counts.items())),
        "tables_by_family": dict(sorted(family_counts.items())),
        "candidate_code_occurrences": sum(code_counts.values()),
        "unique_candidate_codes": len(code_counts),
        "repeated_candidate_codes": len(repeated),
        "repeated_code_examples": dict(
            sorted(repeated.items())[:30]
        ),
        "pages_with_table_overlaps": pages_with_overlaps,
        "overlapping_table_pairs": overlapping_pairs,
    }


def build_report(source: dict, pages: list[dict]) -> dict:
    summary = summarize_pages(pages)
    finished = len(pages) == source["page_count"]

    if not finished:
        status = "partial"
    elif summary["scan_error_pages"]:
        status = "complete_with_errors"
    else:
        status = "complete"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source": source,
        "summary": summary,
        "pages": pages,
    }


def validate_checkpoint(payload: dict, source: dict) -> list[dict]:
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("source") != source
        or payload.get("status") != "partial"
    ):
        raise RuntimeError(
            "Checkpoint does not match the current PDF or schema"
        )

    pages = payload.get("pages")

    if not isinstance(pages, list):
        raise RuntimeError("Invalid checkpoint pages")

    numbers = [
        page.get("page_number")
        for page in pages
        if isinstance(page, dict)
    ]

    if numbers != list(range(1, len(pages) + 1)):
        raise RuntimeError("Checkpoint page sequence is invalid")

    if len(pages) >= source["page_count"]:
        raise RuntimeError("Checkpoint must be incomplete")

    return pages


def run_scan(max_new_pages: int | None = None) -> dict:
    configured = os.environ.get("ARKEMX_PDF")

    if not configured:
        raise RuntimeError("ARKEMX_PDF is not configured")

    source_path = Path(configured).resolve()

    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    report_path = DEFAULT_REPORT
    checkpoint_path = report_path.with_suffix(".partial.json")
    lock_path = report_path.with_suffix(".lock")

    with pymupdf.open(source_path) as doc:
        source = source_fingerprint(source_path, len(doc))

        if report_path.exists():
            try:
                cached = json.loads(
                    report_path.read_text(encoding="utf-8")
                )

                if (
                    cached.get("schema_version") == SCHEMA_VERSION
                    and cached.get("source") == source
                    and cached.get("status") == "complete"
                    and len(cached.get("pages", [])) == len(doc)
                ):
                    print("CACHE HIT: Existing completed report")
                    print("Report:", report_path)
                    return cached
            except (ValueError, TypeError, OSError):
                pass

        report_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            lock_fd = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise RuntimeError(
                "Another scan may be active; lock exists"
            ) from exc

        try:
            pages = []

            if checkpoint_path.exists():
                checkpoint = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                pages = validate_checkpoint(checkpoint, source)
                print("RESUME FROM PAGE:", len(pages) + 1)

            total = len(doc)
            newly_scanned = 0

            try:
                for number in range(len(pages) + 1, total + 1):
                    try:
                        result = analyze_page(doc[number - 1], number)
                    except Exception as exc:
                        result = {
                            "page_number": number,
                            "table_count": 0,
                            "tables": [],
                            "overlaps": [],
                            "error": (
                                f"{type(exc).__name__}: {exc}"
                            ),
                        }

                    pages.append(result)
                    newly_scanned += 1

                    if number % 5 == 0 or number == total:
                        atomic_write(
                            checkpoint_path,
                            build_report(source, pages),
                        )
                        print(
                            f"PROGRESS {number}/{total}",
                            flush=True,
                        )

                    if (
                        max_new_pages is not None
                        and newly_scanned >= max_new_pages
                    ):
                        break

            except KeyboardInterrupt:
                atomic_write(
                    checkpoint_path,
                    build_report(source, pages),
                )
                print("SCAN INTERRUPTED - checkpoint saved")
                raise

            current_stat = source_path.stat()

            if (
                current_stat.st_size != source["size_bytes"]
                or current_stat.st_mtime_ns != source["mtime_ns"]
            ):
                raise RuntimeError(
                    "PDF changed during scanning; report not finalized"
                )

            report = build_report(source, pages)

            if report["status"] == "partial":
                atomic_write(checkpoint_path, report)
                print(
                    f"PARTIAL: {len(pages)}/{total} pages saved"
                )
            else:
                atomic_write(report_path, report)
                checkpoint_path.unlink(missing_ok=True)

                print("SCAN STATUS:", report["status"])
                print("REPORT:", report_path)

            print(
                json.dumps(
                    report["summary"],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return report

        finally:
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-new-pages",
        type=int,
        default=None,
    )
    args = parser.parse_args()

    if args.max_new_pages is not None:
        if args.max_new_pages < 1:
            parser.error("--max-new-pages must be positive")

    run_scan(max_new_pages=args.max_new_pages)


if __name__ == "__main__":
    main()
