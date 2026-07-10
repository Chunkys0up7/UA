"""
Pytest entrypoint for the YAML scenarios.

`pytest` discovers this file, parametrizes over every scenario, and
runs each through `EvalRunner`. CI fails if any scenario fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.framework import EvalCase, EvalRunner, load_scenarios

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def _ids(case: EvalCase) -> str:
    return case.name


@pytest.mark.eval
@pytest.mark.parametrize("case", load_scenarios(SCENARIOS_DIR), ids=_ids)
async def test_scenario(case: EvalCase) -> None:
    runner = EvalRunner()
    result = await runner.run_one(case)
    assert result.passed, "\n".join(result.failures) or "scenario failed"
