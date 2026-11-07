"""Suite hygiene: every test module must work when run on its own."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


class SuiteHygieneTests(unittest.TestCase):
    def test_every_test_module_imports_helpers_first(self) -> None:
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = []
            for node in tree.body:
                if isinstance(node, ast.Import):
                    modules += [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.module != "__future__":
                    modules.append(node.module)
            if not any(m.startswith("context_bridge") for m in modules):
                continue
            first_project_import = next(m for m in modules if m == "helpers" or m.startswith("context_bridge"))
            self.assertEqual(first_project_import, "helpers", f"{path.name} must import helpers before context_bridge")


if __name__ == "__main__":
    unittest.main()
