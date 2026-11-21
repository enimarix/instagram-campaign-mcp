"""Step 172: the style catalog (src/studio/style_catalog.py). Studio styles (faked registry)
merged with a tiny fake Lemo-Opuscar library; favourites; ✦ styles not selectable; the
preview fetch (respx, no network) and the API."""

import json
import os

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.studio import style_catalog as sc
from src.studio import styles

from .conftest import LOCAL
from .test_api_assets import _settings
from .test_styles import ALL, _fake_registry


def _style(root, slug, title, quote, **meta):
    d = root / "styles" / slug
    d.mkdir(parents=True)
    d.joinpath("STYLE.md").write_text(
        f"# {title} — Style Prompt\n\n> {quote}\n> References (grammar only): none.\n\n## 1. Essence\n",
        "utf-8")
    if meta:
        d.joinpath("style.json").write_text(json.dumps({"slug": slug, **meta}), "utf-8")


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "lemo"
    _style(root, "watercolor", "Watercolor Brush", "Wet paint blooms on paper. It moves.",
           en="Watercolor Brush", category_en="Painting & Illustration", uses=["Travel"])
    _style(root, "manga-panels", "Manga Panels", "Black-and-white panels cut like film.",
           category_en="Cartoons", needs=["image-generation"])
    _style(root, "rubber-hose", "1930s Rubber Hose Cartoon", "Every object swings to jazz.",
           category_en="Cartoons", uses=["Ads"])
    _style(root, "_template", "Style Name", "One or two sentences.")
    (root / "styles" / "README.md").write_text("# index", "utf-8")
    return root


@pytest.fixture
def settings(lib):
    return _settings(lemo_library=str(lib))


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    _fake_registry(monkeypatch)
    monkeypatch.setattr(styles, "SAMPLES_DIR", tmp_path / "samples")
    monkeypatch.setattr(sc, "PREVIEWS_DIR", tmp_path / "previews")


def test_catalog_merges_studio_and_lemo(store, settings):
    cat = sc.catalog(store, settings)
    ids = [e["id"] for e in cat]
    assert ids[:len(ALL)] == ALL  # studio first, registry order
    # Lemo by category then name; _template and README skipped
    assert ids[len(ALL):] == ["lemo:rubber-hose", "lemo:manga-panels", "lemo:watercolor"]
    by = {e["id"]: e for e in cat}
    w = by["lemo:watercolor"]
    assert (w["family"], w["label"], w["essence"]) == ("lemo", "Watercolor Brush",
                                                       "Wet paint blooms on paper.")
    assert (w["category"], w["tags"], w["selectable"], w["why_not"]) == (
        "Painting & Illustration", ["Travel"], True, None)
    assert w["credit"]["licence"] == "CC BY 4.0" and "Lemomo" in w["credit"]["text"]
    assert w["preview"] == {"poster": None, "clip": None} and w["favourite"] is False
    m = by["lemo:manga-panels"]
    assert not m["selectable"] and "✦" in m["why_not"]
    v = by["voxel"]
    assert (v["family"], v["label"], v["selectable"], v["credit"]) == ("studio", "3D 8-bit",
                                                                       True, None)
    assert v["essence"]


def test_missing_library_lists_studio_only(store):
    assert [e["id"] for e in sc.catalog(store, _settings())] == ALL


def test_disabled_studio_style_not_selectable(store, settings):
    styles.set_choice(store, "voxel", enabled=False)
    v = sc.get_entry(store, settings, "voxel")
    assert not v["selectable"] and v["why_not"] == sc.DISABLED


def test_filters(store, settings):
    def ids(**kw):
        return [e["id"] for e in sc.catalog(store, settings, **kw)]

    assert ids(family="studio") == ALL
    assert ids(family="lemo", q="cartoons") == ["lemo:rubber-hose", "lemo:manga-panels"]
    assert ids(q="JAZZ swings") == ["lemo:rubber-hose"]
    assert ids(q="travel") == ["lemo:watercolor"]
    with pytest.raises(ValueError):
        sc.catalog(store, settings, family="other")


def test_favourites_come_first(store, settings):
    assert sc.set_favourite(store, settings, "lemo:watercolor", True)["favourite"]
    sc.set_favourite(store, settings, "paper", True)
    cat = sc.catalog(store, settings)
    assert [e["id"] for e in cat[:2]] == ["paper", "lemo:watercolor"]  # family order kept
    assert [e["id"] for e in sc.catalog(store, settings, favourites_only=True)] == [
        "paper", "lemo:watercolor"]
    assert not sc.set_favourite(store, settings, "paper", False)["favourite"]
    assert sc.favourites(store) == ["lemo:watercolor"]
    with pytest.raises(ValueError):
        sc.set_favourite(store, settings, "lemo:nope", True)
    with pytest.raises(ValueError):
        sc.set_favourite(store, settings, "nope", True)


def test_parse_is_cached_by_mtime(store, settings, lib):
    sc.lemo_styles(settings)
    hits = sc._parse.cache_info().hits
    sc.lemo_styles(settings)
    assert sc._parse.cache_info().hits >= hits + 3
    md = lib / "styles" / "watercolor" / "STYLE.md"
    md.write_text("# Aquarelle — Style Prompt\n\n> Nouvelle essence.\n", "utf-8")
    st = md.stat()
    os.utime(md, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    w = {e["id"]: e for e in sc.lemo_styles(settings)}["lemo:watercolor"]
    assert (w["label"], w["essence"]) == ("Aquarelle", "Nouvelle essence.")


@respx.mock
def test_fetch_previews(settings, tmp_path):
    poster = respx.get(url__regex=r".*/media/thumb/(watercolor|rubber-hose)-960\.webp").mock(
        return_value=httpx.Response(200, content=b"webp"))
    respx.get(url__regex=r".*/media/thumb/manga-panels-960\.webp").mock(
        return_value=httpx.Response(404))
    out = sc.fetch_previews(settings)
    assert (out["fetched"], out["kept"]) == (2, 0)
    assert out["failed"] == [{"id": "lemo:manga-panels", "kind": "poster", "error": "HTTP 404"}]
    assert (tmp_path / "previews" / "watercolor" / "poster.webp").read_bytes() == b"webp"
    assert sc.preview_file("lemo:watercolor", "poster") is not None
    calls = poster.call_count
    out = sc.fetch_previews(settings, slugs=["lemo:watercolor"])  # kept, not fetched again
    assert (out["fetched"], out["kept"], poster.call_count) == (0, 1, calls)
    big = respx.get(url__regex=r".*/watercolor\.mp4").mock(return_value=httpx.Response(
        200, content=b"x", headers={"content-length": str(sc.CLIP_MAX_MB * 2**20 + 1)}))
    out = sc.fetch_previews(settings, slugs=["watercolor"], clips=True)
    assert big.called and out["failed"][0]["kind"] == "clip"
    assert "bigger" in out["failed"][0]["error"]
    assert not list((tmp_path / "previews" / "watercolor").glob("*.part"))
    with pytest.raises(ValueError):
        sc.fetch_previews(settings, slugs=["nope"])


def test_preview_file_refuses_odd_ids(tmp_path):
    (tmp_path / "previews").mkdir()
    for sid in ("watercolor", "lemo:../x", "lemo:", "lemo:A"):
        assert sc.preview_file(sid, "poster") is None
    assert sc.preview_file("lemo:watercolor", "other") is None


def test_api(store, settings, tmp_path):
    with TestClient(create_app(settings, store=store), base_url=LOCAL) as tc:
        body = tc.get("/api/style-catalog").json()
        assert len(body) == len(ALL) + 3
        assert [e["id"] for e in tc.get("/api/style-catalog?family=lemo&q=jazz").json()] == [
            "lemo:rubber-hose"]
        assert tc.get("/api/style-catalog?family=x").status_code == 422
        r = tc.patch("/api/style-catalog/lemo:watercolor", json={"favourite": True})
        assert r.status_code == 200 and r.json()["favourite"]
        favs = tc.get("/api/style-catalog?favourites=true").json()
        assert [e["id"] for e in favs] == ["lemo:watercolor"]
        assert tc.patch("/api/style-catalog/lemo:nope", json={"favourite": True}
                        ).status_code == 422
        assert tc.patch("/api/style-catalog/voxel", json={"fav": 1}).status_code == 422
        url = "/api/style-catalog/lemo:watercolor/preview/poster"
        assert tc.get(url).status_code == 404
        f = tmp_path / "previews" / "watercolor" / "poster.webp"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"webp")
        r = tc.get(url)
        assert r.status_code == 200 and r.content == b"webp"
        assert r.headers["content-type"] == "image/webp"
        w = next(e for e in tc.get("/api/style-catalog").json() if e["id"] == "lemo:watercolor")
        assert w["preview"]["poster"] == url
        assert tc.get("/api/style-catalog/lemo:watercolor/preview/x").status_code == 422


def test_cli_refuses_unknown_slug(capsys):
    from src import scheduler

    with pytest.raises(SystemExit) as e:
        scheduler.main(["styles", "fetch-previews", "nope"])
    assert e.value.code == 1 and "not in the library: nope" in capsys.readouterr().err
