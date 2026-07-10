"""T-TOP-1/2 (graph topology + eligibility provenance) and T-ISO-1
(demographics import isolation) — the structural fair-lending and
human-gate guarantees."""

from __future__ import annotations

import ast
import pathlib

from app.agent.graph import build_underwriter_graph

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


# ---------------------------------------------------------------- T-TOP-1
class TestTopology:
    def test_every_path_passes_human_review(self):
        graph = build_underwriter_graph().get_graph()
        edges = {(e.source, e.target) for e in graph.edges}
        # END is reachable ONLY from human_review — no bypass (HR-2)
        into_end = {source for source, target in edges if target == "__end__"}
        assert into_end == {"human_review"}, into_end
        # underwrite has no edge to END
        assert ("underwrite", "__end__") not in edges

    def test_no_auto_decline_path(self):
        """Declines happen only inside human_review's finalize (with reason
        codes) — no node writes a terminal decision before the gate."""
        graph_src = (APP_DIR / "agent" / "graph.py").read_text(encoding="utf-8")
        underwrite_src = graph_src.split("async def _underwrite")[1].split(
            "async def _human_review")[0]
        assert "finalize(" not in underwrite_src


# ---------------------------------------------------------------- T-TOP-2
class TestEligibilityProvenance:
    def test_only_policy_engine_produces_overall(self):
        """`overall` eligibility is assigned only in policy_engine (grep/AST:
        no other module constructs a RulesResult or writes rollups)."""
        offenders = []
        for py in APP_DIR.rglob("*.py"):
            if "policy_engine" in str(py):
                continue
            source = py.read_text(encoding="utf-8")
            if "RulesResult(" in source:
                offenders.append(str(py))
        assert offenders == [], offenders


# ---------------------------------------------------------------- T-ISO-1
class TestDemographicsIsolation:
    FORBIDDEN_PACKAGES = ("agent", "agents", "policy_engine", "aus",
                          "domain", "audit", "llm", "adapters")

    def _imports(self, path: pathlib.Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        return names

    def test_decisioning_never_imports_demographics(self):
        offenders = []
        for package in self.FORBIDDEN_PACKAGES:
            package_dir = APP_DIR / package
            if not package_dir.exists():
                continue
            for py in package_dir.rglob("*.py"):
                for imported in self._imports(py):
                    if "demographics" in imported or imported == "app.hmda":
                        offenders.append(f"{py}: imports {imported}")
        assert offenders == [], offenders

    def test_decisioning_never_names_the_table(self):
        offenders = []
        for package in self.FORBIDDEN_PACKAGES:
            package_dir = APP_DIR / package
            if not package_dir.exists():
                continue
            for py in package_dir.rglob("*.py"):
                if "hmda_demographics" in py.read_text(encoding="utf-8"):
                    offenders.append(str(py))
        assert offenders == [], offenders

    def test_pipeline_never_sees_demographics(self):
        """strip_demographics removes the block before the pipeline runs."""
        import json
        from app.hmda.demographics import strip_demographics
        package = json.loads(
            (pathlib.Path(__file__).resolve().parents[2] / "data" / "loans" /
             "clean-approve.json").read_text(encoding="utf-8"))
        stripped = strip_demographics(package)
        assert stripped and "b1" in stripped
        assert "hmda_demographics" not in package
