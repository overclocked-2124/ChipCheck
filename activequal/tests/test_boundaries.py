"""Import boundaries from HLD 01 §6.3 and AGENTS.md.

* ``model`` is shared with the bench process and must not depend on planner libraries.
* Decision has no instrument access and must never see the simulator's hidden fault constants.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # .../activequal
REPO = ROOT.parent


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def violations(package: str, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    result = []
    for path in sorted((ROOT / package).rglob("*.py")):
        if "tests" in path.relative_to(ROOT / package).parts:
            continue
        for module in imported_modules(path):
            if module.startswith(forbidden_prefixes):
                result.append(f"{path.relative_to(REPO)} imports {module}")
    return result


class BoundaryTests(unittest.TestCase):
    def test_model_does_not_import_planner_libraries(self) -> None:
        self.assertEqual(violations("model", ("optuna", "torch", "scipy", "numpy")), [])

    def test_importing_model_does_not_load_optuna(self) -> None:
        code = ("import sys, activequal.model.contract, activequal.model.predicates; "
                "sys.exit(1 if any(m == 'optuna' or m.startswith('optuna.') for m in sys.modules) else 0)")
        result = subprocess.run([sys.executable, "-I", "-c", code], cwd=REPO, capture_output=True, text=True,
                                env={"PYTHONPATH": str(REPO)})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_decision_does_not_import_bench_side_code(self) -> None:
        forbidden = ("activequal.adapter", "activequal.controller", "activequal.tools", "activequal.firmware",
                     "activequal.service", "activequal.storage")
        self.assertEqual(violations("decision", forbidden), [])

    def test_model_does_not_import_services(self) -> None:
        forbidden = ("activequal.decision", "activequal.adapter", "activequal.controller", "activequal.service",
                     "activequal.agent", "activequal.storage", "activequal.tools")
        self.assertEqual(violations("model", forbidden), [])


if __name__ == "__main__":
    unittest.main()
