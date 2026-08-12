"""Check that the FDA-label curation workflow is ready to run."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

OPENFDA_DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json?limit=1"


def virtual_environment_status(project_dir: Path) -> tuple[bool, str]:
    """Describe whether the project environment exists and is currently active."""
    active = Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve()
    configured = os.environ.get("VIRTUAL_ENV")
    if active:
        location = Path(configured or sys.prefix).resolve()
        return True, f"active: {location}"

    project_venv = project_dir / ".venv"
    python = project_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if python.exists():
        return False, f"existing but inactive: {project_venv.resolve()}"
    return False, f"absent: {project_venv.resolve()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analyses/curation-candidate"),
        help="Directory that will contain curation runs.",
    )
    parser.add_argument(
        "--skip-network",
        action="store_true",
        help="Skip the read-only openFDA connectivity check.",
    )
    return parser.parse_args()


def run_checks(
    output_dir: Path,
    skip_network: bool = False,
    project_dir: Path | None = None,
) -> list[dict[str, str | bool]]:
    checks: list[dict[str, str | bool]] = []

    venv_ok, venv_detail = virtual_environment_status((project_dir or Path.cwd()).resolve())
    checks.append(
        {
            "name": "virtual environment",
            "ok": venv_ok,
            "detail": venv_detail,
        }
    )

    python_ok = sys.version_info >= (3, 11)
    checks.append(
        {
            "name": "Python 3.11+",
            "ok": python_ok,
            "detail": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        }
    )

    for module_name in ("anthropic", "markitdown", "pydantic", "requests"):
        try:
            importlib.import_module(module_name)
            ok, detail = True, "installed"
        except ImportError:
            ok, detail = False, "missing; run python -m pip install -e ."
        checks.append({"name": f"dependency: {module_name}", "ok": ok, "detail": detail})

    checks.append(
        {
            "name": "ANTHROPIC_API_KEY",
            "ok": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "detail": "set" if os.environ.get("ANTHROPIC_API_KEY") else "missing",
        }
    )

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        probe = output_dir / ".moalmanac-fda-curation-write-check"
        probe.touch(exist_ok=False)
        probe.unlink()
        writable, writable_detail = True, str(output_dir.resolve())
    except OSError as exc:
        writable, writable_detail = False, str(exc)
    checks.append({"name": "output directory", "ok": writable, "detail": writable_detail})

    if skip_network:
        checks.append({"name": "openFDA connectivity", "ok": True, "detail": "skipped"})
    else:
        try:
            with urlopen(OPENFDA_DRUGSFDA_URL, timeout=15) as response:
                status = response.status
            network_ok, network_detail = True, f"HTTP {status}"
        except (OSError, URLError) as exc:
            network_ok, network_detail = False, str(exc)
        checks.append(
            {"name": "openFDA connectivity", "ok": network_ok, "detail": network_detail}
        )

    return checks


def main() -> int:
    args = parse_args()
    checks = run_checks(args.output_dir, skip_network=args.skip_network)
    for check in checks:
        marker = "PASS" if check["ok"] else "FAIL"
        print(f"[{marker}] {check['name']}: {check['detail']}")
    failed = [check for check in checks if not check["ok"]]
    if failed:
        print(f"\n{len(failed)} check(s) failed. No paid model call was made.")
        return 1
    print("\nReady for FDA-label curation. No paid model call was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
