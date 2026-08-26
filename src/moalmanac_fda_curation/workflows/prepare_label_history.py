"""Build historical Indications and Usage changelog and cache artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..core.artifacts import (
    document_label_url,
    load_document_artifact,
    resolve_document_application_number,
)
from ..core.build_section1_changelogs import build_changelog, output_stem


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rebuild existing changelog artifacts after explicit confirmation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    document_path = work_dir / "intermediate" / "document.proposal.json"
    document = load_document_artifact(document_path)
    application = resolve_document_application_number(document)
    brand = document["drug_name_brand"]
    stem = output_stem(brand, application)
    changelog_dir = work_dir / "intermediate" / "section1-changelogs"
    cache_dir = work_dir / "intermediate" / "section1-cache"
    changelog_markdown = changelog_dir / f"{stem}-section1-changelog.md"
    changelog_json = changelog_dir / f"{stem}-section1-changelog.json"
    cache_json = cache_dir / f"{stem}-section1-cache.json"

    existing = [
        path for path in (changelog_markdown, changelog_json) if path.exists()
    ]
    if existing and not args.overwrite:
        if len(existing) == 2 and cache_json.exists():
            print(f"Reusing label history: {changelog_json}")
            print(f"Indications and Usage cache: {cache_json}")
            return 0
        paths = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"Incomplete label-history artifacts already exist: {paths}. "
            "Use --overwrite after confirming regeneration."
        )

    build_changelog(
        brand_name=brand,
        application_number=application,
        current_label_url=document_label_url(document),
        output_dir=changelog_dir,
        cache_dir=cache_dir,
        historical_labels_dir=work_dir / "historical-labels",
    )
    if not cache_json.exists():
        raise FileNotFoundError(f"Label-history cache was not created: {cache_json}")
    print(f"Label history: {changelog_json}")
    print(f"Indications and Usage cache: {cache_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
