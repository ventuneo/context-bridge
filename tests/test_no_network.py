"""Static guarantee: the package never imports networking modules."""

from __future__ import annotations

import ast
import unittest

from helpers import SCRIPTS_DIR

FORBIDDEN = {"socket", "ssl", "urllib", "http", "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio",
             "requests", "httpx", "aiohttp"}  # fmt: skip


class NoNetworkTests(unittest.TestCase):
    def test_package_imports_no_network_modules(self) -> None:
        files = sorted((SCRIPTS_DIR / "context_bridge").rglob("*.py")) + [SCRIPTS_DIR / "cb.py"]
        self.assertGreater(len(files), 5)
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module]
                for name in names:
                    self.assertNotIn(name.split(".")[0], FORBIDDEN, f"{path.name} imports {name}")


if __name__ == "__main__":
    unittest.main()
