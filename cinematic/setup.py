"""Download the cinematic engine's tools into cinematic/tools/ (git-ignored, about 1.6 GB).

    python cinematic/setup.py

Skips what is already there, so it is safe to re-run. Sources and licences: cinematic/README.md.
ponytail: Windows builds only (the studio machine); add the Linux Blender / Rhubarb archives
if the worker ever runs elsewhere.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent / "tools"
DL = TOOLS / "dl"
BLENDER = TOOLS / "blender-5.2.4-windows-x64"
MPFB = BLENDER / "portable" / "extensions" / ".user" / "user_default" / "mpfb"
MH = "https://files.makehumancommunity.org"
TEXTURES = ("WoodFloor051", "Wood049", "Fabric061", "Wallpaper001A")
HDRI = "belfast_sunset_puresky_1k.hdr"
MODELS = TOOLS / "models"
# Props for future sets (CC0). Poly Haven glTF at 1k textures (ps2ify crushes them anyway).
POLYHAVEN = (
    # kitchen
    "electric_stove", "vintage_microwave", "vintage_electric_kettle", "modern_wooden_cabinet",
    "drawer_cabinet", "wooden_cutting_board", "pot_enamel_01", "brass_pan_01", "jug_01",
    "wooden_bowl_01", "wooden_spoon", "tea_set_01", "wicker_basket_01",
    # food
    "food_apple_01", "food_avocado_01", "bananas", "sweet_potato", "lemon", "food_lime_01",
    "yellow_onion", "croissant", "hamburger_buns", "carrot_cake", "long_life_food",
)
KENNEY = ("furniture-kit", "food-kit")  # kitchen fridge, stove, counters...; 200 foods
ITCH = {"polytoon-gym": "https://comphonia.itch.io/unity-asset-polytoon-gym"}  # dumbbells, plates, bench, rack, bike
UA = {"User-Agent": "growth-studio-setup"}


def fetch(url: str, name: str) -> Path:
    path = DL / name
    if not path.is_file():
        DL.mkdir(parents=True, exist_ok=True)
        print("download", url, flush=True)
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req) as r, open(path.with_suffix(".part"), "wb") as f:
            shutil.copyfileobj(r, f)
        path.with_suffix(".part").replace(path)
    return path


def unzip(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():  # no path escapes out of dest
            if not (dest / member).resolve().is_relative_to(dest.resolve()):
                raise RuntimeError(f"{zip_path.name}: unsafe path {member!r}")
        z.extractall(dest)


def unity_package(pkg: Path, dest: Path) -> None:
    """A .unitypackage is a tar.gz of <guid>/{pathname, asset}: write each asset under its
    path (models, textures), minus Unity's own files."""
    with tarfile.open(pkg, "r:gz") as t:
        files = {m.name: m for m in t.getmembers() if m.isfile()}
        for name, member in files.items():
            if not name.endswith("/pathname"):
                continue
            asset = files.get(name[: -len("pathname")] + "asset")
            rel = t.extractfile(member).read().decode("utf-8").splitlines()[0]
            out = (dest / rel).resolve()
            if asset is None or rel.endswith((".meta", ".cs", ".unity", ".prefab", ".mat", ".asset")):
                continue
            if not out.is_relative_to(dest.resolve()):
                raise RuntimeError(f"{pkg.name}: unsafe path {rel!r}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(t.extractfile(asset).read())


def get_json(url: str, opener=urllib.request.urlopen, data: bytes | None = None,
             referer: str | None = None) -> dict:
    headers = {**UA, **({"Referer": referer} if referer else {})}
    with opener(urllib.request.Request(url, data=data, headers=headers)) as r:
        return json.load(r)


def session() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def polyhaven(name: str) -> None:
    dest = MODELS / "polyhaven" / name
    if dest.is_dir():
        return
    gltf = get_json(f"https://api.polyhaven.com/files/{name}")["gltf"]["1k"]["gltf"]
    files = {f"{name}.gltf": gltf["url"], **{k: v["url"] for k, v in gltf["include"].items()}}
    tmp = dest.with_suffix(".part")
    for rel, url in files.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req) as r, open(tmp / rel, "wb") as f:
            shutil.copyfileobj(r, f)
    tmp.rename(dest)


def kenney(slug: str) -> None:
    """kenney.nl's own download button: a fresh signed link per request (needs the page's
    cookie and referer)."""
    dest = MODELS / "kenney" / slug
    if not dest.is_dir():
        page, jar = f"https://kenney.nl/assets/{slug}", session()
        jar.open(urllib.request.Request(page, headers=UA)).close()
        link = get_json(f"https://kenney.nl/download-link/{f'assets/{slug}'.encode().hex()}",
                        jar.open, referer=page)["url"]
        unzip(fetch(link, f"kenney-{slug}.zip"), dest)


def itch(name: str, page: str) -> None:
    """A free / pay-what-you-want itch.io pack, the "no thanks, just take me to the downloads" way."""
    dest = MODELS / name
    if dest.is_dir():
        return
    jar = session()
    download_page = get_json(f"{page}/download_url", jar.open, b"")["url"]
    with jar.open(urllib.request.Request(download_page, headers=UA)) as r:
        html = r.read().decode("utf-8", "replace")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    for upload in dict.fromkeys(re.findall(r'data-upload_id="(\d+)"', html)):
        url = get_json(f"{page}/file/{upload}?source=view_game&as_props=1&after_download_lightbox=true",
                       jar.open, urllib.parse.urlencode({"csrf_token": csrf}).encode())["url"]
        unzip(fetch(url, f"{name}-{upload}.zip"), dest)
    for pkg in dest.glob("*.unitypackage"):
        unity_package(pkg, dest)


def main() -> None:
    if not BLENDER.is_dir():
        unzip(fetch("https://download.blender.org/release/Blender5.2/blender-5.2.4-windows-x64.zip",
                    "blender.zip"), TOOLS)
    (BLENDER / "portable").mkdir(exist_ok=True)  # keeps Blender's prefs and extensions here
    if not MPFB.is_dir():
        unzip(fetch("https://extensions.blender.org/download/sha256:c075b3e9b94b8e5556a5f03f4653602d02ea306de08126e8f55ed6dee28a2dad/add-on-mpfb-v2.0.18.zip",
                    "mpfb.zip"), MPFB)
        for url in (f"{MH}/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip",
                    f"{MH}/functional/visemes02.zip", f"{MH}/functional/faceunits01.zip"):
            unzip(fetch(url, url.rsplit("/", 1)[1]), MPFB / "data")
        subprocess.run([str(BLENDER / "blender.exe"), "-b", "--python-expr",
                        "import bpy; bpy.ops.preferences.addon_enable(module='bl_ext.user_default.mpfb');"
                        " bpy.ops.wm.save_userpref()"], check=True)
    if not (TOOLS / "Rhubarb-Lip-Sync-1.14.0-Windows").is_dir():
        unzip(fetch("https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/"
                    "Rhubarb-Lip-Sync-1.14.0-Windows.zip", "rhubarb.zip"), TOOLS)
    if not (TOOLS / "anim").is_dir():
        unzip(fetch("https://opengameart.org/sites/default/files/universal_animation_librarystandard.zip",
                    "anim.zip"), TOOLS / "anim")
    tex = TOOLS / "tex"
    for name in TEXTURES:
        if not (tex / name).is_dir():
            unzip(fetch(f"https://ambientcg.com/get?file={name}_1K-JPG.zip", f"{name}.zip"), tex / name)
    if not (tex / HDRI).is_file():
        shutil.copyfile(fetch(f"https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/{HDRI}", HDRI),
                        tex / HDRI)
    for name in POLYHAVEN:
        polyhaven(name)
    for slug in KENNEY:
        kenney(slug)
    for name, page in ITCH.items():
        itch(name, page)
    print("cinematic tools ready in", TOOLS)


if __name__ == "__main__":
    sys.exit(main())
