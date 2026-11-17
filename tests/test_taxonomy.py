import json

import pytest

from src.taxonomy import (
    DEFAULT_PATH,
    TaxonomyError,
    load_taxonomy,
    valid_values,
    validate,
    validate_many,
)


def _write(tmp_path, data):
    path = tmp_path / "taxonomy.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _vocab(*ids):
    return {"values": [{"id": i, "label": i} for i in ids]}


def test_committed_file_loads():
    taxonomy = load_taxonomy()
    assert DEFAULT_PATH.is_file()
    assert isinstance(taxonomy["version"], int)
    assert valid_values("tracks") == ["remix", "motion"]
    assert taxonomy["pillars"]["placeholder"] is True
    for kind in ("hook_types", "templates", "feedback_reasons"):
        assert valid_values(kind)
    assert "PixelSkit" in valid_values("templates")
    assert all(e.get("description") for e in taxonomy["hook_types"]["values"])


def test_validate_known_values():
    assert validate("tracks", "motion") == "motion"
    assert validate_many("feedback_reasons", ("weak_hook", "other")) == ["weak_hook", "other"]
    assert validate_many("hook_types", []) == []


def test_unknown_value_lists_valid_ones():
    with pytest.raises(TaxonomyError) as e:
        validate("tracks", "inapp")
    assert isinstance(e.value, ValueError)
    assert "'inapp'" in str(e.value) and "remix, motion" in str(e.value)


def test_validate_many_reports_all_bad_values():
    with pytest.raises(TaxonomyError) as e:
        validate_many("hook_types", ["question", "nope", "pov", "nada"])
    msg = str(e.value)
    assert "'nope'" in msg and "'nada'" in msg and "bold_claim" in msg
    with pytest.raises(TypeError):
        validate_many("hook_types", "pov")


@pytest.mark.parametrize("kind", ["tags", "version"])
def test_unknown_kind(kind):
    with pytest.raises(TaxonomyError, match="unknown taxonomy kind.*valid kinds: tracks"):
        valid_values(kind)


def test_custom_path(tmp_path):
    path = _write(tmp_path, {"version": 2, "moods": _vocab("calm", "hype")})
    assert validate("moods", "hype", path) == "hype"
    with pytest.raises(TaxonomyError, match="valid: calm, hype"):
        validate("moods", "sad", str(path))


@pytest.mark.parametrize(
    "data, match",
    [
        ("{not json", "invalid JSON"),
        ([], "top level must be an object"),
        ({"tracks": _vocab("a")}, "version"),
        ({"version": 1}, "no vocabularies"),
        ({"version": 1, "tracks": ["remix"]}, "non-empty 'values'"),
        ({"version": 1, "tracks": {"values": []}}, "non-empty 'values'"),
        ({"version": 1, "tracks": {"values": ["remix"]}}, "must be an object"),
        ({"version": 1, "tracks": _vocab("remix", "remix")}, "duplicate id 'remix'"),
        ({"version": 1, "tracks": _vocab("Remix")}, "not snake_case"),
        ({"version": 1, "templates": _vocab("fact_quest")}, "not PascalCase"),
        ({"version": 1, "tracks": {"values": [{"id": "remix"}]}}, "label"),
    ],
)
def test_malformed_file(tmp_path, data, match):
    with pytest.raises(TaxonomyError, match=match):
        load_taxonomy(_write(tmp_path, data))


def test_missing_file(tmp_path):
    with pytest.raises(TaxonomyError, match="not found"):
        load_taxonomy(tmp_path / "missing.json")
