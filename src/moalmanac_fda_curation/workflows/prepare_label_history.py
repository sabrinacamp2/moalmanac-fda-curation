"""Build historical Indications and Usage changelog and cache artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import NamedTuple

from ..core.artifacts import (
    document_label_url,
    load_document_artifact,
    resolve_document_application_number,
)
from ..core.build_section1_changelogs import build_changelog, output_stem


class LabelHistoryPaths(NamedTuple):
    changelog_json: Path
    cache_json: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rebuild existing changelog artifacts after explicit confirmation.",
    )
    return parser.parse_args()


def prepare_label_history(
    work_dir: Path,
    *,
    overwrite: bool = False,
    baseline_label_url: str | None = None,
) -> LabelHistoryPaths:
    work_dir = work_dir.resolve()
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
    if existing and not overwrite:
        if len(existing) == 2 and cache_json.exists():
            return LabelHistoryPaths(changelog_json, cache_json)
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
        baseline_label_url=baseline_label_url,
    )
    if not cache_json.exists():
        raise FileNotFoundError(f"Label-history cache was not created: {cache_json}")
    return LabelHistoryPaths(changelog_json, cache_json)


def main() -> int:
    args = parse_args()
    paths = prepare_label_history(args.work_dir, overwrite=args.overwrite)
    print(f"Label history: {paths.changelog_json}")
    print(f"Indications and Usage cache: {paths.cache_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
