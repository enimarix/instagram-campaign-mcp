"""
Controlled vocabularies for tags (GOAL.md §3.5).

`brand/taxonomy.json` lists every value the studio accepts for track, pillar, hook
type, template and feedback reason. Store methods, MCP tools and API routes call
`validate()` / `validate_many()` so a typo is rejected with the list of valid values
instead of silently splitting a breakdown.

File shape: `{"version": <int>, "<kind>": {"values": [{"id", "label", ...}], ...}}`.
Every top-level key except `version` is a vocabulary (a "kind"). Ids are snake_case,
except `templates`, whose ids are PascalCase (they name motion/ components).
Vocabulary-level extras such as `note` or `placeholder` are allowed and ignored here.

The default file is `APP_HOME/brand/taxonomy.json`: the project folder for a source
checkout or an editable install. A regular `pip install` does not ship `brand/`, so
there you must set IG_MCP_HOME to a folder holding `brand/taxonomy.json` or pass a path.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from src.config import APP_HOME

DEFAULT_PATH = APP_HOME / "brand" / "taxonomy.json"

SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
PASCAL_CASE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
ID_RULES = {"templates": PASCAL_CASE}  # every other kind: SNAKE_CASE


class TaxonomyError(ValueError):
    """An unknown kind or value, or a malformed taxonomy file."""


def _check(data: Any, path: Path) -> Dict[str, Any]:
    def fail(msg: str) -> TaxonomyError:
        return TaxonomyError(f"{path}: {msg}")

    if not isinstance(data, dict):
        raise fail("top level must be an object")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise fail("'version' must be a positive integer")
    kinds = [k for k in data if k != "version"]
    if not kinds:
        raise fail("no vocabularies")
    for kind in kinds:
        vocab = data[kind]
        values = vocab.get("values") if isinstance(vocab, dict) else None
        if not isinstance(values, list) or not values:
            raise fail(f"'{kind}' must be an object with a non-empty 'values' list")
        rule = ID_RULES.get(kind, SNAKE_CASE)
        seen = set()
        for i, entry in enumerate(values):
            if not isinstance(entry, dict):
                raise fail(f"'{kind}' value #{i} must be an object")
            ident, label = entry.get("id"), entry.get("label")
            if not isinstance(ident, str) or not rule.match(ident):
                style = "PascalCase" if rule is PASCAL_CASE else "snake_case"
                raise fail(f"'{kind}' value #{i}: id {ident!r} is not {style}")
            if not isinstance(label, str) or not label.strip():
                raise fail(f"'{kind}' value '{ident}' needs a non-empty 'label'")
            if ident in seen:
                raise fail(f"'{kind}' has duplicate id '{ident}'")
            seen.add(ident)
    return data


@lru_cache(maxsize=None)
def _load(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TaxonomyError(f"taxonomy file not found: {path}") from None
    except json.JSONDecodeError as e:
        raise TaxonomyError(f"{path}: invalid JSON: {e}") from None
    return _check(data, path)


def load_taxonomy(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load and schema-check the taxonomy (cached per path). Treat the result as read-only."""
    return _load(Path(path).resolve() if path else DEFAULT_PATH)


def valid_values(kind: str, path: Optional[Union[str, Path]] = None) -> List[str]:
    """Ids of one vocabulary, in file order."""
    taxonomy = load_taxonomy(path)
    if kind == "version" or kind not in taxonomy:
        kinds = ", ".join(k for k in taxonomy if k != "version")
        raise TaxonomyError(f"unknown taxonomy kind {kind!r}; valid kinds: {kinds}")
    return [entry["id"] for entry in taxonomy[kind]["values"]]


def validate_many(
    kind: str, values: Iterable[str], path: Optional[Union[str, Path]] = None
) -> List[str]:
    """Return `values` as a list, or raise TaxonomyError naming every unknown one."""
    allowed = valid_values(kind, path)
    values = list(values)
    bad = [v for v in values if v not in allowed]
    if bad:
        raise TaxonomyError(
            f"unknown {kind} value(s): {', '.join(map(repr, bad))}; "
            f"valid: {', '.join(allowed)}"
        )
    return values


def validate(kind: str, value: str, path: Optional[Union[str, Path]] = None) -> str:
    """Return `value`, or raise TaxonomyError listing the valid ones."""
    return validate_many(kind, [value], path)[0]
