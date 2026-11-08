"""Layered configuration: built-in defaults < user config < project config.

* The **user config** (``$CONTEXT_BRIDGE_CONFIG`` or
  ``$XDG_CONFIG_HOME/context-bridge/config.toml``) belongs to the person running the
  tool. It may set deny roots, allowed external locations and limits.
* The **project config** (``<root>/.context-bridge/config.toml``) comes from a possibly
  untrusted repository, so it can only *tighten*: add excludes, lower limits, turn PII
  redaction on, and request external sources that the user config already allows.
* The hard rules in ``policy.py`` cannot be configured at all.

Example user config::

    [privacy]
    deny_roots = ["~/private-notes", "~/work/confidential"]
    allowed_external_roots = ["~/notes/projects"]
    redact_pii = true

    [scan]
    max_file_bytes = 262144

    [setup]
    protected_roots = ["~/notes"]   # setup never writes CLAUDE.md or settings below these

    [hook]
    sources = ["startup", "resume"]  # session starts the optional auto-resume hook answers
    max_tokens = 400                 # size limit of the digest it loads (300 to 2000)
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import compat, safepath
from .errors import ConfigError, UnsafePathError
from .policy import DEFAULT_INCLUDE, DenyRoots

PROJECT_CONFIG_REL = ".context-bridge/config.toml"
MAX_CONFIG_BYTES = 64 * 1024
DEFAULT_MAX_FILE_BYTES = 256 * 1024
DEFAULT_MAX_TOTAL_BYTES = 2 * 1024 * 1024
_LIMIT_BOUNDS = {
    "max_file_bytes": (1, 16 * 1024 * 1024),
    "max_total_bytes": (1, 64 * 1024 * 1024),
    "max_tokens": (300, 2000),  # the status lines and the coverage alone take about 250
}
HOOK_SOURCES = ("startup", "resume", "clear", "compact")

_USER_KEYS = {
    "privacy": {"deny_roots", "allowed_external_roots", "redact_pii"},
    "setup": {"protected_roots"},
    "hook": {"sources", "max_tokens"},
    "scan": {"include", "exclude", "max_file_bytes", "max_total_bytes"},
}
_PROJECT_KEYS = {
    "privacy": {"redact_pii"},
    "scan": {"include", "exclude", "max_file_bytes", "max_total_bytes"},
    "sources": {"external"},
}
_USER_ONLY = {
    ("privacy", "deny_roots"),
    ("privacy", "allowed_external_roots"),
    ("setup", "protected_roots"),
    ("hook", "sources"),
    ("hook", "max_tokens"),
}


@dataclass(frozen=True)
class Config:
    deny_roots: tuple[Path, ...] = ()
    allowed_external_roots: tuple[Path, ...] = ()
    external_sources: tuple[Path, ...] = ()
    protected_roots: tuple[Path, ...] = ()  # setup never writes below these
    hook_sources: tuple[str, ...] = ("startup", "resume")  # session starts the auto-resume hook answers
    hook_max_tokens: int = 400
    include: tuple[tuple[str, str], ...] = DEFAULT_INCLUDE
    exclude: tuple[str, ...] = ()
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES
    redact_pii: bool = True
    user_config_path: Path | None = None
    project_config_loaded: bool = False
    warnings: tuple[str, ...] = field(default=())

    def deny(self) -> DenyRoots:
        return DenyRoots(self.deny_roots)


def user_config_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    explicit = env.get("CONTEXT_BRIDGE_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    return compat.config_home(env) / "context-bridge" / "config.toml"


def _parse(text: str, origin: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {origin}: {exc}") from exc


def _check_keys(data: dict[str, Any], allowed: dict[str, set[str]], origin: str, warnings: list[str]) -> None:
    for section, values in data.items():
        if not isinstance(values, dict):
            warnings.append(f"{origin}: '{section}' is not a table, ignored")
            continue
        for key in values:
            if (section, key) in _USER_ONLY and section in allowed and key not in allowed[section]:
                warnings.append(f"{origin}: '{section}.{key}' is only allowed in the user config, ignored")
            elif key not in allowed.get(section, set()):
                warnings.append(f"{origin}: unknown setting '{section}.{key}', ignored")


def _get(data: dict[str, Any], section: str, key: str, allowed: dict[str, set[str]]) -> Any:
    if key not in allowed.get(section, set()):
        return None
    table = data.get(section)
    return table.get(key) if isinstance(table, dict) else None


def _str_list(value: Any, name: str, origin: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{origin}: '{name}' must be a list of non-empty strings")
    return value


def _paths(value: Any, name: str, origin: str) -> list[Path]:
    return [Path(v).expanduser() for v in _str_list(value, name, origin)]


def _limit(value: Any, name: str, origin: str) -> int | None:
    if value is None:
        return None
    low, high = _LIMIT_BOUNDS[name]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ConfigError(f"{origin}: '{name}' must be an integer between {low} and {high}")
    return value


def _bool(value: Any, name: str, origin: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ConfigError(f"{origin}: '{name}' must be true or false")
    return value


def _hook_sources(value: Any, origin: str) -> tuple[str, ...]:
    sources = _str_list(value, "hook.sources", origin)
    unknown = [s for s in sources if s not in HOOK_SOURCES]
    if unknown:
        raise ConfigError(f"{origin}: 'hook.sources' may only contain {', '.join(HOOK_SOURCES)}")
    return tuple(sources)


def _includes(value: Any, origin: str) -> list[tuple[str, str]]:
    return [(pattern, "custom") for pattern in _str_list(value, "scan.include", origin)]


def _read_user_config(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError(f"cannot read user config: {exc}") from exc
    if len(text) > MAX_CONFIG_BYTES:
        raise ConfigError("user config is larger than 64 KiB")
    return text


def _read_project_config(root: Path) -> str | None:
    try:
        content = safepath.read_file(root, PROJECT_CONFIG_REL, MAX_CONFIG_BYTES)
    except UnsafePathError as exc:
        if exc.reason == safepath.MISSING:
            return None
        raise ConfigError(f"project config refused ({exc.reason})") from exc
    text, valid = safepath.decode_text(content.data)
    if not valid:
        raise ConfigError("project config is not valid UTF-8")
    return text


def load_config(root: Path, user_path: Path | None = None, include_project: bool = True) -> Config:
    """Load and merge the configuration for project ``root``.

    With ``include_project=False`` nothing inside ``root`` is read, so callers can check
    deny roots before touching the project at all.
    """
    warnings: list[str] = []
    cfg = Config()
    user_path = user_path or user_config_path()

    user_text = _read_user_config(user_path)
    if user_text is not None:
        origin = "user config"
        data = _parse(user_text, origin)
        _check_keys(data, _USER_KEYS, origin, warnings)
        include_extra = _includes(_get(data, "scan", "include", _USER_KEYS), origin)
        cfg = replace(
            cfg,
            deny_roots=tuple(_paths(_get(data, "privacy", "deny_roots", _USER_KEYS), "privacy.deny_roots", origin)),
            allowed_external_roots=tuple(
                _paths(_get(data, "privacy", "allowed_external_roots", _USER_KEYS), "allowed_external_roots", origin)
            ),
            include=tuple(include_extra) + cfg.include,
            exclude=tuple(_str_list(_get(data, "scan", "exclude", _USER_KEYS), "scan.exclude", origin)),
            max_file_bytes=_limit(_get(data, "scan", "max_file_bytes", _USER_KEYS), "max_file_bytes", origin)
            or cfg.max_file_bytes,
            max_total_bytes=_limit(_get(data, "scan", "max_total_bytes", _USER_KEYS), "max_total_bytes", origin)
            or cfg.max_total_bytes,
            redact_pii=_bool(_get(data, "privacy", "redact_pii", _USER_KEYS), "redact_pii", origin)
            if _get(data, "privacy", "redact_pii", _USER_KEYS) is not None
            else cfg.redact_pii,
            protected_roots=tuple(
                _paths(_get(data, "setup", "protected_roots", _USER_KEYS), "setup.protected_roots", origin)
            ),
            hook_sources=_hook_sources(_get(data, "hook", "sources", _USER_KEYS), origin) or cfg.hook_sources,
            hook_max_tokens=_limit(_get(data, "hook", "max_tokens", _USER_KEYS), "max_tokens", origin)
            or cfg.hook_max_tokens,
            user_config_path=user_path,
        )

    project_text = _read_project_config(root) if include_project else None
    if project_text is not None:
        origin = "project config"
        data = _parse(project_text, origin)
        _check_keys(data, _PROJECT_KEYS, origin, warnings)
        file_limit = _limit(_get(data, "scan", "max_file_bytes", _PROJECT_KEYS), "max_file_bytes", origin)
        total_limit = _limit(_get(data, "scan", "max_total_bytes", _PROJECT_KEYS), "max_total_bytes", origin)
        for name, requested, current in (
            ("max_file_bytes", file_limit, cfg.max_file_bytes),
            ("max_total_bytes", total_limit, cfg.max_total_bytes),
        ):
            if requested is not None and requested > current:
                warnings.append(f"{origin}: '{name}' can only be lowered, keeping {current}")
        pii = _bool(_get(data, "privacy", "redact_pii", _PROJECT_KEYS), "redact_pii", origin)
        if pii is False and cfg.redact_pii:
            warnings.append(f"{origin}: 'redact_pii' can only be switched on, keeping true")
        cfg = replace(
            cfg,
            include=tuple(_includes(_get(data, "scan", "include", _PROJECT_KEYS), origin)) + cfg.include,
            exclude=cfg.exclude
            + tuple(_str_list(_get(data, "scan", "exclude", _PROJECT_KEYS), "scan.exclude", origin)),
            max_file_bytes=min(cfg.max_file_bytes, file_limit or cfg.max_file_bytes),
            max_total_bytes=min(cfg.max_total_bytes, total_limit or cfg.max_total_bytes),
            redact_pii=cfg.redact_pii or bool(pii),
            external_sources=tuple(
                _paths(_get(data, "sources", "external", _PROJECT_KEYS), "sources.external", origin)
            ),
            project_config_loaded=True,
        )
    return replace(cfg, warnings=tuple(warnings))
