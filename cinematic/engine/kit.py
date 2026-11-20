"""Materials + low-poly geometry shared by every set.

PS2 rule of thumb used everywhere: few polygons, flat-shaded hard objects, small textures
sampled with nearest filtering. Modern touches the reference also has: roughness and
normal maps, glossy ceramics, soft light.
"""
import math
import os

import bpy
from mathutils import Vector

ENGINE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ENGINE, "assets")
TOOLS = os.environ.get("CINEMATIC_TOOLS") or os.path.join(ENGINE, "..", "tools")  # cinematic/setup.py
TEX = os.path.join(TOOLS, "tex")
MODELS = os.path.join(TOOLS, "models")


def asset(name):
    return os.path.join(ASSETS, name)


def mpfb():
    """MPFB's services. setup.py unpacks MPFB into its user-data folder (extensions/.user/
    user_default/mpfb) and the portable Blender has no saved prefs: point the user repo there
    and enable it for this run only (nothing is saved)."""
    try:
        from bl_ext.user_default.mpfb import services
        return services
    except ModuleNotFoundError:
        pass
    import addon_utils
    bpy.context.preferences.use_preferences_save = False
    repo = next(r for r in bpy.context.preferences.extensions.repos if r.module == "user_default")
    repo.use_custom_directory = True
    repo.custom_directory = os.path.join(bpy.utils.user_resource("EXTENSIONS"), ".user", "user_default")
    addon_utils.enable("bl_ext.user_default.mpfb", default_set=True)
    from bl_ext.user_default.mpfb import services
    return services


def _image(path, px, colorspace):
    key = f"{os.path.basename(path)}@{px}"
    img = bpy.data.images.get(key)
    if img:
        return img
    img = bpy.data.images.load(path)
    img.name = key
    img.colorspace_settings.name = colorspace
    if px and max(img.size) > px:                       # PS2-sized copy, made in memory
        img.scale(px, max(1, px * img.size[1] // img.size[0]))
    return img


def mat(name, color=(0.8, 0.8, 0.8), *, image=None, cg=None, tile=None, px=256, rough=0.85, normal=0.5,
        metal=0.0, alpha=1.0, emit=0.0, coat=0.0, spec=0.5, tint=None, uv=False):
    """color: flat base color. image: our texture file. cg: ambientCG set name (color/rough/normal).
    tile: repeats per meter with world-box projection (no UVs needed); uv=True uses mesh UVs."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt, links = m.node_tree, m.node_tree.links
    p = nt.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    p.inputs["Specular IOR Level"].default_value = spec
    if coat:
        p.inputs["Coat Weight"].default_value = coat
        p.inputs["Coat Roughness"].default_value = 0.15

    vec = None
    if image or cg:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        vec = tc.outputs["UV" if uv else "Object"]
        if tile:
            mp = nt.nodes.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (tile, tile, tile)
            links.new(vec, mp.inputs["Vector"])
            vec = mp.outputs["Vector"]

    def tex(path, colorspace="sRGB", size=px):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = _image(path, size, colorspace)
        n.interpolation = "Closest"
        if not uv:
            n.projection, n.projection_blend = "BOX", 0.0
        links.new(vec, n.inputs["Vector"])
        return n

    color_out = None
    if image:
        t = tex(image)
        color_out = t.outputs["Color"]
        if alpha == "texture":
            links.new(t.outputs["Alpha"], p.inputs["Alpha"])
    if cg:
        base = os.path.join(TEX, cg, f"{cg}_1K-JPG_")
        if not image:
            color_out = tex(base + "Color.jpg").outputs["Color"]
        if os.path.exists(base + "Roughness.jpg"):
            links.new(tex(base + "Roughness.jpg", "Non-Color").outputs["Color"], p.inputs["Roughness"])
        if normal:
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.inputs["Strength"].default_value = normal
            links.new(tex(base + "NormalGL.jpg", "Non-Color", 512).outputs["Color"], nm.inputs["Color"])
            links.new(nm.outputs["Normal"], p.inputs["Normal"])
    if color_out is not None and tint:
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
        mix.inputs[0].default_value = 1.0
        links.new(color_out, mix.inputs[6])
        mix.inputs[7].default_value = (*tint, 1)
        color_out = mix.outputs[2]
    if color_out is not None:
        links.new(color_out, p.inputs["Base Color"])
    if emit:
        p.inputs["Emission Strength"].default_value = emit
        if color_out is not None:
            links.new(color_out, p.inputs["Emission Color"])
        else:
            p.inputs["Emission Color"].default_value = (*color, 1)
    if alpha == "texture":
        m.surface_render_method = "DITHERED"            # alpha-clipped cards, sorted correctly
    elif alpha < 1:
        p.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "BLENDED"
    return m


# ---------------- geometry ----------------

def _finish(o, m, smooth=False, parent=None):
    o.data.materials.append(m)
    for poly in o.data.polygons:
        poly.use_smooth = smooth
    if parent:
        o.parent = parent
    return o


def box(name, size, loc, m, rot=(0, 0, 0), parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name, o.scale = name, size
    bpy.ops.object.transform_apply(scale=True)
    return _finish(o, m, parent=parent)


def cyl(name, r, h, loc, m, verts=8, r2=None, smooth=False, parent=None):
    """r = top radius, r2 = bottom radius (cone/bowl/plate shapes)."""
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r2 if r2 is not None else r, radius2=r, depth=h, location=loc)
    o = bpy.context.object
    o.name = name
    return _finish(o, m, smooth, parent)


def blob(name, size, loc, m, sub=1, smooth=False, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=sub, radius=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name, o.scale = name, size
    return _finish(o, m, smooth)


def ellipsoid(name, size, loc, m, segs=10, rings=7, smooth=True, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segs, ring_count=rings, radius=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name, o.scale = name, size
    return _finish(o, m, smooth)


def plane(name, size, loc, m, rot=(math.radians(90), 0, 0)):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name, o.scale = name, (*size, 1)
    return _finish(o, m)


def folded(name, start, end, top, bottom, out, m, folds=6, amp=0.025, flare=0.0, cols=None):
    """Hanging fabric (tablecloth skirt, curtain): a strip from start->end (x,y), z top->bottom,
    zig-zag folds along its length, bottom pushed `flare` toward `out` (unit x,y). Flat-shaded
    facets make the folds read like PS2 cloth."""
    cols = cols or folds * 4
    a, b, o = Vector((*start, 0)), Vector((*end, 0)), Vector((*out, 0))
    verts, faces = [], []
    for i in range(cols + 1):
        t = i / cols
        p = a.lerp(b, t)
        wave = amp * math.sin(t * folds * 2 * math.pi)
        verts.append((*(p + o * wave)[:2], top))
        verts.append((*(p + o * (wave * 1.6 + flare))[:2], bottom))
    for i in range(cols):
        faces.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return _finish(ob, m)


def empty(name, loc, rot_z=0.0):
    e = bpy.data.objects.new(name, None)
    e.location, e.rotation_euler = loc, (0, 0, rot_z)
    bpy.context.collection.objects.link(e)
    return e


def prop(rel, loc=(0, 0, 0), rot_z=0.0, height=None, scale=None, center=False):
    """Import a downloaded model (`tools/models/<rel>`: .glb/.gltf or .fbx) under one empty,
    standing on `loc` and scaled so it is `height` m tall (or by `scale`; neither: as modelled).
    Kenney models come small (a fridge is 0.92), so give them a height. center: its footprint's
    centre on `loc` (packs whose origin is a corner). Returns the empty."""
    path = os.path.join(MODELS, rel)
    before = set(bpy.data.objects)
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    pack = os.path.join(MODELS, rel.replace("\\", "/").split("/")[0])
    found = [os.path.join(d, f) for d, _, fs in os.walk(pack) for f in fs
             if f.lower().endswith((".png", ".jpg", ".jpeg", ".tga"))]
    for img in bpy.data.images:  # FBX packs point at the author's paths: find by name,
        if img.filepath and not os.path.isfile(bpy.path.abspath(img.filepath)):  # or the only one
            name = os.path.basename(img.filepath.replace("\\", "/")).lower()
            hit = next((f for f in found if os.path.basename(f).lower() == name),
                       found[0] if len(found) == 1 else None)
            if hit:
                img.filepath = hit
                img.reload()
    root = empty(os.path.splitext(os.path.basename(rel))[0], (0, 0, 0))
    for o in new:
        if o.parent is None:
            o.parent = root
    bpy.context.view_layer.update()
    corners = [o.matrix_world @ Vector(c) for o in new if o.type == "MESH" for c in o.bound_box]
    lo = min(c.z for c in corners)
    k = height / (max(c.z for c in corners) - lo) if height else scale or 1.0
    root.scale = (k, k, k)
    cx, cy = ((min(c.x for c in corners) + max(c.x for c in corners)) / 2 * k,
              (min(c.y for c in corners) + max(c.y for c in corners)) / 2 * k) if center else (0, 0)
    cos, sin = math.cos(rot_z), math.sin(rot_z)
    root.location = (loc[0] - cx * cos + cy * sin, loc[1] - cx * sin - cy * cos,
                     (loc[2] if len(loc) > 2 else 0.0) - lo * k)
    root.rotation_euler.z = rot_z
    return root


KENNEY_SCALE = 1.95  # Kenney's furniture kit at real size (its fridge is 0.92 tall)


def kenney(name, loc, rot_deg=0, scale=KENNEY_SCALE):
    """A Kenney Furniture Kit model (`name`.glb) at real size."""
    return prop(f"kenney/furniture-kit/Models/GLTF format/{name}.glb", loc, math.radians(rot_deg), scale=scale, center=True)


def gym(name, loc, rot_deg=0, height=None):
    """A Polytoon Gym model (`name`.FBX), `height` m tall."""
    return prop(f"polytoon-gym/Assets/Polytoon Gym/Gym/Models/{name}.FBX", loc, math.radians(rot_deg), height, center=True)


def room(wall, floor, ceiling=None, back=1.5, left=-2.6, right=None, h=2.8):
    """A room open toward the camera (-Y): floor, back wall at y=back, side wall(s) at x=left
    (and x=right), maybe a ceiling."""
    box("floor", (12, 12, 0.1), (0, -2, -0.05), floor)
    box("wall_back", (12, 0.12, h), (0, back + 0.06, h / 2), wall)
    for side, x in (("left", left), ("right", right)):
        if x is not None:
            box(f"wall_{side}", (0.12, 12, h), (x + math.copysign(0.06, x), back - 6, h / 2), wall)
    if ceiling:
        box("ceiling", (12, 12, 0.1), (0, -2, h + 0.05), ceiling)


def lamp(name, loc, color=(1.0, 0.68, 0.38), energy=60, radius=0.2):
    """A warm point light (a practical: pendant, fridge glow, candle)."""
    light = bpy.data.lights.new(name, "POINT")
    light.color, light.energy, light.shadow_soft_size = color, energy, radius
    o = bpy.data.objects.new(name, light)
    o.location = loc
    bpy.context.collection.objects.link(o)
    return o
