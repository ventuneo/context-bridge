"""Command-line interface: argument parsing, dispatch and exit codes."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from . import __version__
from .errors import EXIT_ERROR, EXIT_USAGE, ContextBridgeError

Handler = Callable[[argparse.Namespace], int]


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that exits with EX_USAGE (64) instead of 2 on bad input."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="context-bridge",
        description="Extract, compress, verify and restore project context for AI sessions.",
    )
    parser.add_argument("--version", action="version", version=f"context-bridge {__version__}")
    parser.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        return handler(args)
    except ContextBridgeError as exc:
        print(f"context-bridge: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return EXIT_ERROR
