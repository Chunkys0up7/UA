"""
CLI entrypoint for running evals.

    python -m evals.runner

Loads every scenario in `evals/scenarios/`, runs it, prints a report,
and exits non-zero if any case failed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from evals.framework import EvalRunner, load_scenarios

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


async def _main() -> int:
    cases = load_scenarios(SCENARIOS_DIR)
    if not cases:
        print(f"No scenarios found in {SCENARIOS_DIR}")
        return 0
    runner = EvalRunner()
    report = await runner.run_all(cases)
    print(report.render())
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
