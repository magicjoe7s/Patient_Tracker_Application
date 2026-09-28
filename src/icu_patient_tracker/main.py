"""Executable entry point for the ICU Patient Tracker."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path


def main(arguments: Sequence[str] | None = None) -> int:
    """Start the desktop application."""
    process_arguments = list(arguments or sys.argv)
    if "--smoke-test" in process_arguments:
        flag_position = process_arguments.index("--smoke-test")
        if flag_position != 1 or len(process_arguments) != 3:
            print("usage: icu-patient-tracker --smoke-test WORK_DIRECTORY", file=sys.stderr)
            return 2
        from icu_patient_tracker.app.smoke_test import run_smoke_test

        return run_smoke_test(Path(process_arguments[2]))

    from icu_patient_tracker.app.bootstrap import run_application

    return run_application(process_arguments)


if __name__ == "__main__":
    raise SystemExit(main())
