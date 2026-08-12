"""Prepare FDA document metadata and its deterministic curator review."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from .curate_doc_from_drugsfda_endpoint import curate_document
from .workflow_artifacts import write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-number", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--accessed-date",
        type=lambda value: datetime.strptime(value, "%Y-%m-%d").date(),
        default=date.today(),
    )
    parser.add_argument("--company")
    parser.add_argument("--label-url")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    document_path = work_dir / "intermediate" / "document.proposal.json"
    if document_path.exists():
        raise FileExistsError(f"Document proposal already exists: {document_path}")

    document = curate_document(args)
    write_json_atomic(document_path, document)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "moalmanac_fda_curation.review_packet",
            "--stage",
            "document",
            "--document-json",
            str(document_path),
            "--output-dir",
            str(work_dir / "review"),
        ],
        check=True,
    )
    print(f"Document proposal: {document_path}")
    print(f"Document review: {work_dir / 'review' / 'document.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
