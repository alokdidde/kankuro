"""ccreator: a JSON-speaking character creator CLI for AI agents.

Every command prints exactly one JSON object on stdout:
  {"ok": true, "command": "...", ...}             on success (exit code 0)
  {"ok": false, "error": {"code", "message", "hint"}} on failure (exit code 2 = bad input, 1 = internal)
Blender's own log goes to <project>/build/blender.log, never to stdout.
"""
import argparse
import json
import os
import sys
import time
import traceback

from . import catalog, morph, spec as specmod
from .errors import CliError

VERSION = "0.1.0"


def emit(obj, code=0):
    sys.stdout.write(json.dumps(obj, indent=None if os.environ.get("CCREATOR_COMPACT") else 2, default=str) + "\n")
    sys.stdout.flush()
    return code


def _project(a):
    return os.path.abspath(a.project or os.environ.get("CCREATOR_PROJECT") or ".")


def _log(project):
    d = os.path.join(project, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "blender.log")


# ---------------------------------------------------------------- project / spec commands

def cmd_init(a):
    p = os.path.abspath(a.dir)
    if os.path.exists(specmod.project_path(p)) and not a.force:
        raise CliError("exists", f"{specmod.project_path(p)} already exists", hint="Pass --force to overwrite")
    os.makedirs(p, exist_ok=True)
    s = specmod.default_spec(a.name or os.path.basename(p), a.preset)
    specmod.save(p, s)
    return {"project": p, "spec": s}


def cmd_show(a):
    p = _project(a)
    s = specmod.load(p)
    out = {"project": p, "spec": s}
    builds = os.path.join(p, "build", "manifest.json")
    if os.path.exists(builds):
        out["last_build"] = json.load(open(builds))
    return out


def cmd_set(a):
    p = _project(a)
    s = specmod.load(p)
    changed = {}
    for item in a.assignments:
        if "=" not in item:
            raise CliError("bad_assignment", f"Expected path=value, got '{item}'",
                           hint="e.g. body.macros.gender=0.8 skin.color=#8d5524 body.height_cm=180")
        k, v = item.split("=", 1)
        val = specmod.parse_value(v)
        s = specmod.set_path(s, k.strip(), val)
        changed[k.strip()] = val
    specmod.save(p, s)
    return {"changed": changed, "spec": s}


def cmd_catalog(a):
    out = {
        "presets": specmod.PRESETS,
        "body_sliders": {k: {"default": round(d, 4), "range": [0, 1], "desc": desc} for k, (d, desc) in morph.MACROS.items()},
        "hair_styles": {k: v["desc"] for k, v in catalog.HAIR_STYLES.items()},
        "garments": {k: {"desc": v["desc"], "slot": v["slot"], "layer": v["layer"], "fabric": v.get("fabric")}
                     for k, v in catalog.GARMENTS.items()},
        "fabrics": {k: v["desc"] for k, v in __import__("ccreator.fabric", fromlist=["FABRICS"]).FABRICS.items()},
        "detail_morphs": f"{len(morph.modifier_catalog())} modifiers; list with `ccreator morphs`",
        "animations": "list with `ccreator animations`",
    }
    if a.section:
        if a.section not in out:
            raise CliError("bad_section", f"Unknown section '{a.section}'", hint=f"Valid: {', '.join(out)}")
        return {a.section: out[a.section]}
    return out


def cmd_morphs(a):
    cat = morph.modifier_catalog()
    items = []
    for name, c in sorted(cat.items()):
        if a.group and c["group"] != a.group:
            continue
        if a.search and a.search.lower() not in name.lower():
            continue
        items.append({"name": name, "group": c["group"], "range": c["range"]})
    groups = sorted({c["group"] for c in cat.values()})
    return {"count": len(items), "groups": groups, "modifiers": items,
            "usage": "ccreator set body.morphs.<name>=<value>  (e.g. body.morphs.nose/nose-scale-horiz-decr|incr=0.4)"}


def cmd_hair(a):
    p = _project(a)
    s = specmod.load(p)
    if a.action == "remove":
        s["hair"] = None
    elif a.action == "set":
        if a.style not in catalog.HAIR_STYLES:
            raise CliError("unknown_hair", f"Unknown hair style '{a.style}'",
                           hint=f"Valid: {', '.join(catalog.HAIR_STYLES)}")
        h = {"style": a.style, "color": specmod.color(a.color, "color") or (s["hair"] or {}).get("color") or "#3b2a1e"}
        if a.texture:
            h["texture"] = specmod.import_file(p, a.texture, "textures")
        s["hair"] = h
    elif a.action == "import":
        if not a.file:
            raise CliError("missing_arg", "hair import needs --file <mesh>")
        h = {"style": "custom", "source": specmod.import_file(p, a.file, "meshes"),
             "color": specmod.color(a.color, "color")}
        if a.texture:
            h["texture"] = specmod.import_file(p, a.texture, "textures")
        s["hair"] = h
    specmod.save(p, s)
    return {"hair": s["hair"]}


def _garment(s, gid):
    for g in s["garments"]:
        if g["id"] == gid:
            return g
    raise CliError("no_garment", f"No garment with id '{gid}'",
                   hint="Current ids: " + (", ".join(g["id"] for g in s["garments"]) or "(none)"))


def cmd_garment(a):
    p = _project(a)
    s = specmod.load(p)
    if a.action in ("add", "import"):
        if a.action == "add":
            if a.type not in catalog.GARMENTS:
                raise CliError("unknown_garment", f"Unknown garment type '{a.type}'",
                               hint=f"Valid: {', '.join(catalog.GARMENTS)}")
            gid = a.id or a.type
            g = {"id": gid, "type": a.type}
        else:
            if not a.file or not a.id:
                raise CliError("missing_arg", "garment import needs --file <mesh> and --id <name>")
            gid = a.id
            g = {"id": gid, "type": "custom", "source": specmod.import_file(p, a.file, "meshes")}
        if any(x["id"] == gid for x in s["garments"]):
            raise CliError("duplicate_garment", f"Garment id '{gid}' already exists",
                           hint="Pass --id <new id>, or use `garment set` to change it")
        slot = catalog.GARMENTS.get(g["type"], {}).get("slot")
        replaced = []
        if slot and not a.keep_slot:
            for x in list(s["garments"]):
                if catalog.GARMENTS.get(x["type"], {}).get("slot") == slot:
                    s["garments"].remove(x)
                    replaced.append(x["id"])
        s["garments"].append(g)
    else:
        g = _garment(s, a.id or a.type)
        if a.action == "remove":
            s["garments"].remove(g)
            specmod.save(p, s)
            return {"removed": g["id"], "garments": s["garments"]}
        replaced = []
    if a.color is not None:
        g["color"] = specmod.color(a.color, "color")
    if a.texture is not None:
        g["texture"] = specmod.import_file(p, a.texture, "textures") if a.texture else None
    if a.layer is not None:
        g["layer"] = a.layer
    if a.hide_body is not None:
        g["hide_body"] = a.hide_body == "true"
    if a.roughness is not None:
        g["roughness"] = a.roughness
    if a.fabric is not None:
        from . import fabric
        if a.fabric not in fabric.FABRICS and a.fabric != "none":
            raise CliError("unknown_fabric", f"Unknown fabric '{a.fabric}'",
                           hint="Valid: none, " + ", ".join(fabric.FABRICS))
        g["fabric"] = a.fabric
    for key, kind in (("normal", "textures"), ("height", "textures")):
        val = getattr(a, key)
        if val is not None:
            g[key] = specmod.import_file(p, val, kind) if val else None
    if a.normal_strength is not None:
        g["normal_strength"] = a.normal_strength
    specmod.save(p, s)
    out = {"garment": g, "garments": s["garments"]}
    if replaced:
        out["replaced"] = replaced
    return out


# ---------------------------------------------------------------- Blender-backed commands

def _bpy():
    try:
        import bpy  # noqa: F401
    except ImportError as e:
        raise CliError("no_blender", f"Blender's Python module is not importable: {e}",
                       hint="pip install bpy (needs the Python version bpy was built for; bpy 5.2 = Python 3.13)",
                       exit_code=1)


def _parse_list(x):
    if not x:
        return []
    return [v.strip() for v in x.split(",") if v.strip()]


FOCUS = {
    "head": lambda lo, hi: ((lo[0], lo[1], hi[2] - (hi[2] - lo[2]) * 0.16), (hi[0], hi[1], hi[2])),
    "upper": lambda lo, hi: ((lo[0], lo[1], hi[2] - (hi[2] - lo[2]) * 0.5), (hi[0], hi[1], hi[2])),
}


def _focus_bbox(b, focus):
    if focus in (None, "full"):
        return None
    from .blender import render, util
    import numpy as np
    lo, hi = render._bbox([b.body])
    if focus in FOCUS:
        lo2, hi2 = FOCUS[focus](lo, hi)
        if focus == "head":
            c = np.array([0.0, (lo[1] + hi[1]) / 2])
            r = (hi2[2] - lo2[2]) / 2
            return (np.array([c[0] - r, lo[1], lo2[2]]), np.array([c[0] + r, hi[1], hi2[2]]))
        return (np.array(lo2), np.array(hi2))
    raise CliError("bad_focus", f"Unknown focus '{focus}'", hint="full, upper or head")


def cmd_build(a):
    _bpy()
    from .blender import build, render, util
    p = _project(a)
    s = specmod.load(p)
    out_path = os.path.abspath(a.out or os.path.join(p, "build", f"{s['name']}.glb"))
    work = os.path.join(p, "build", "work")
    os.makedirs(work, exist_ok=True)
    anims = _parse_list(a.animations) if a.animations is not None else s["export"].get("animations", [])
    t0 = time.time()
    with util.quiet(_log(p)):
        b = build.build_scene(s, p, work)
        info = build.summary(b)
        renders = None
        if a.render:
            paths, sheet = render.render_views([m for m in b.meshes], os.path.join(p, "renders"),
                                               size=a.size, samples=a.samples, prefix="build")
            renders = {"views": paths, "sheet": sheet}
        clips = build.export_glb(b, out_path, anims)
    manifest = {
        "glb": out_path, "bytes": os.path.getsize(out_path), "animations": clips,
        "seconds": round(time.time() - t0, 2), "timings": b.timings, **info,
        "hidden_body_faces": getattr(b, "hidden_faces", 0), "warnings": b.warnings,
    }
    if renders:
        manifest["renders"] = renders
    json.dump(manifest, open(os.path.join(p, "build", "manifest.json"), "w"), indent=2)
    return manifest


def cmd_render(a):
    _bpy()
    from .blender import anim, build, render, util
    p = _project(a)
    s = specmod.load(p)
    work = os.path.join(p, "build", "work")
    os.makedirs(work, exist_ok=True)
    views = _parse_list(a.views) or ["front", "three_quarter", "side", "back"]
    bad = [v for v in views if v not in render.VIEWS]
    if bad:
        raise CliError("bad_view", f"Unknown view(s): {', '.join(bad)}", hint=f"Valid: {', '.join(render.VIEWS)}")
    with util.quiet(_log(p)):
        b = build.build_scene(s, p, work)
        frame = None
        if a.animation:
            frame = anim.pose_at(b.arm, a.animation, a.frame)
        bbox = _focus_bbox(b, a.focus)
        prefix = a.prefix or ("pose_" + a.animation if a.animation else "render")
        paths, sheet = render.render_views(b.meshes, os.path.abspath(a.out or os.path.join(p, "renders")),
                                           views=views, size=a.size, samples=a.samples, prefix=prefix, bbox=bbox)
    return {"views": dict(zip(views, paths)), "sheet": sheet, "animation": a.animation, "frame": frame,
            "focus": a.focus or "full",
            "tip": "Open the sheet image to check the result visually"}


def cmd_template(a):
    """UV template sheets for garments (and the body skin) so textures can be repainted externally."""
    _bpy()
    from .blender import build, garments, util
    from . import textures
    p = _project(a)
    s = specmod.load(p)
    out_dir = os.path.abspath(a.out or os.path.join(p, "templates"))
    os.makedirs(out_dir, exist_ok=True)
    targets = a.targets or ["all"]
    work = os.path.join(p, "build", "work")
    os.makedirs(work, exist_ok=True)
    # Build a throwaway spec holding the requested standard garment types
    tmp = json.loads(json.dumps(s))
    want_types, results = [], {}
    for t in targets:
        if t == "all":
            want_types += [g["type"] for g in s["garments"] if not g.get("source")]
            if not s["garments"]:
                want_types += list(catalog.GARMENTS)
            want_types.append("body")
        elif t == "body" or t in catalog.GARMENTS:
            want_types.append(t)
        else:
            g = _garment(s, t)
            if g.get("source"):
                raise CliError("custom_garment", f"'{t}' is an imported mesh; it keeps its own UVs",
                               hint="Export its UVs from the tool that made it")
            want_types.append(g["type"])
    want_types = list(dict.fromkeys(want_types))
    tmp["garments"] = [{"id": t, "type": t} for t in want_types if t != "body"]
    tmp["hair"] = None
    tmp["export"]["hide_body_under_clothes"] = False
    with util.quiet(_log(p)):
        b = build.build_scene(tmp, p, work)
        for m in b.meshes:
            gid = m.get("garment_id")
            if not gid:
                continue
            path = os.path.join(out_dir, f"{gid}_template.png")
            mask = os.path.join(out_dir, f"{gid}_mask.png")
            info = b.uv_info.get(gid, {})
            if info.get("labels"):
                textures.uv_template(garments.uv_polygons(m), path, f"ccreator {gid} UV template ({info['layout']})",
                                     size=a.size, mask_out=mask, labels=info["labels"], divider=False)
            else:
                textures.uv_template(garments.uv_polygons(m), path, f"ccreator {gid} UV template - left: front view, right: back view (seen from behind)",
                                     size=a.size, mask_out=mask)
            results[gid] = {"template": path, "mask": mask, "layout": info.get("layout", "front_back_flat_sketch"),
                            "size": a.size}
    if "body" in want_types:
        from . import morph as mm
        import numpy as np
        faces, fuvs = mm.faces_of_group("body")
        uvs = mm.base()["uvs"]
        polys = [[tuple(uvs[i]) for i in fu] for fu in fuvs]
        path = os.path.join(out_dir, "body_template.png")
        mask = os.path.join(out_dir, "body_mask.png")
        textures.uv_template(polys, path, "ccreator body skin UV template (MakeHuman UV layout)", size=a.size,
                             labels=(), mask_out=mask)
        results["body"] = {"template": path, "mask": mask, "layout": "makehuman_body"}
    return {"templates": results,
            "how_to_retexture": "Paint/generate a same-size image over the template (keep the garment inside the "
                                "grey area; the mask is white where pixels are used), then run "
                                "`ccreator garment set <id> --texture <png>` (or `ccreator set skin.texture` via "
                                "`ccreator skin --texture <png>` for the body)."}


def cmd_skin(a):
    p = _project(a)
    s = specmod.load(p)
    if a.color:
        s["skin"]["color"] = specmod.color(a.color, "color")
    if a.texture is not None:
        s["skin"]["texture"] = specmod.import_file(p, a.texture, "textures") if a.texture else None
    if a.brow_color:
        s["skin"]["brow_color"] = specmod.color(a.brow_color, "brow_color")
    specmod.save(p, s)
    return {"skin": s["skin"]}


def cmd_animations(a):
    _bpy()
    from .blender import anim, util
    with util.quiet():
        util.reset_scene()
        clips = anim.list_clips()
    return {"library": "Mesh2Motion human-base (CC0)", "count": len(clips), "clips": clips,
            "usage": "ccreator build --animations Idle_A,Jog   (or --animations all)"}


def cmd_reference_body(a):
    _bpy()
    import bpy
    from .blender import build, body, util
    p = os.path.abspath(a.out)
    with util.quiet():
        util.reset_scene()
        res = body.build({}, {}, None)
        bo = body.make_group_object(res, "body", "ReferenceBody")
        for o in bpy.data.objects:
            o.select_set(o in (bo, res.arm) if a.with_rig else o == bo)
        if not a.with_rig:
            bo.modifiers.clear()
            bo.parent = None
        bpy.ops.export_scene.gltf(filepath=p, export_format="GLB", use_selection=True, export_skins=a.with_rig)
    return {"glb": p, "note": "Neutral T-pose body (feet at z=0, facing -Y in Blender / +Z in glTF). Model custom "
                             "garments or hair on top of it, export as GLB/OBJ, then `ccreator garment import` / "
                             "`ccreator hair import`; they are conformed and skinned to any body shape."}


def cmd_autorig(a):
    _bpy()
    from .blender import autorig, util
    src = os.path.abspath(a.mesh)
    if not os.path.isfile(src):
        raise CliError("missing_file", f"File not found: {src}")
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    log = os.path.join(os.path.dirname(out), "autorig.log")
    with util.quiet(log):
        r = autorig.run(src, out, facing=a.facing, animations=_parse_list(a.animations),
                        render_dir=os.path.abspath(a.render) if a.render else None, method=a.method)
    return r


def cmd_validate(a):
    _bpy()
    from .blender import validate, util
    with util.quiet():
        r = validate.check(os.path.abspath(a.glb))
    return r


def cmd_schema(a):
    return {"version": VERSION, "commands": SCHEMA, "spec_file": specmod.SPEC_FILE,
            "conventions": {
                "units": "metres; feet on the ground at z=0",
                "facing": "-Y in Blender, +Z in glTF",
                "rest_pose": "T-pose matching Mesh2Motion rig-human",
                "skeleton": "Mesh2Motion human: 65 bones, Unreal-style names (pelvis, spine_01..03, clavicle_l, ...)",
                "output": "one JSON object per command on stdout",
            }}


SCHEMA = {
    "init <dir> [--preset P] [--name N] [--force]": "create a project with character.json",
    "show": "print the spec and last build manifest",
    "set <path>=<value> ...": "edit the spec: body.macros.<slider>, body.morphs.<modifier>, body.height_cm, skin.*, eyes.iris_color, name",
    "catalog [section]": "presets, body sliders, hair styles, garment types",
    "morphs [--group G] [--search S]": "list the detailed morph modifiers (face, torso, limbs...)",
    "skin [--color HEX] [--texture PNG|''] [--brow-color HEX]": "skin tone or a painted skin texture (body UV template)",
    "hair set <style> [--color HEX] [--texture PNG]": "procedural hair style",
    "hair import --file MESH [--color HEX] [--texture PNG]": "custom hair mesh authored on the reference body",
    "hair remove": "bald",
    "garment add <type> [--id ID] [--color HEX] [--texture PNG] [--layer N] [--keep-slot]": "add a standard garment (replaces others in its slot unless --keep-slot)",
    "garment import --file MESH --id ID [--texture PNG] [--color HEX]": "custom garment authored on the reference body",
    "garment set <id> [--color HEX] [--texture PNG|''] [--fabric NAME|none] [--normal PNG] [--height PNG] [--normal-strength F] [--layer N] [--hide-body true|false]": "change a garment; texture = albedo, height/normal add 3D relief on the same UV template",
    "garment remove <id>": "remove a garment",
    "template [targets...] [--out DIR] [--size PX]": "write UV template + mask PNGs (garment ids/types, 'body', or 'all')",
    "build [--out GLB] [--animations A,B|all] [--render]": "build and export the rigged GLB",
    "render [--views front,three_quarter,side,back] [--focus full|upper|head] [--animation CLIP --frame 0..1]": "preview PNGs",
    "animations": "list Mesh2Motion clips that can be baked into the GLB",
    "reference-body --out GLB [--with-rig]": "neutral body for authoring custom garments/hair",
    "autorig <mesh> --out GLB [--facing auto|-y|+y|-x|+x] [--animations A,B] [--render DIR]": "rig any humanoid mesh to the Mesh2Motion skeleton",
    "validate <glb>": "check a GLB against the Mesh2Motion human standard",
    "schema": "this description",
}


def parser():
    ap = argparse.ArgumentParser(prog="ccreator", description="Character creator CLI (JSON output).")
    ap.add_argument("-p", "--project", help="project directory (default: $CCREATOR_PROJECT or cwd)")
    ap.add_argument("--version", action="version", version=VERSION)
    sp = ap.add_subparsers(dest="cmd", required=True)

    x = sp.add_parser("init")
    x.add_argument("dir")
    x.add_argument("--preset", default="neutral")
    x.add_argument("--name")
    x.add_argument("--force", action="store_true")
    sp.add_parser("show")
    x = sp.add_parser("set")
    x.add_argument("assignments", nargs="+")
    x = sp.add_parser("catalog")
    x.add_argument("section", nargs="?")
    x = sp.add_parser("morphs")
    x.add_argument("--group")
    x.add_argument("--search")
    x = sp.add_parser("skin")
    x.add_argument("--color")
    x.add_argument("--texture")
    x.add_argument("--brow-color")

    x = sp.add_parser("hair")
    x.add_argument("action", choices=["set", "import", "remove"])
    x.add_argument("style", nargs="?")
    x.add_argument("--color")
    x.add_argument("--texture")
    x.add_argument("--file")

    x = sp.add_parser("garment")
    x.add_argument("action", choices=["add", "import", "set", "remove"])
    x.add_argument("type", nargs="?", help="garment type (add) or id (set/remove)")
    x.add_argument("--id")
    x.add_argument("--file")
    x.add_argument("--color")
    x.add_argument("--texture")
    x.add_argument("--layer", type=int)
    x.add_argument("--roughness", type=float)
    x.add_argument("--hide-body", choices=["true", "false"])
    x.add_argument("--fabric", help="surface detail preset (see `catalog fabrics`) or 'none'")
    x.add_argument("--normal", help="tangent-space normal map PNG (OpenGL/+Y) on the garment UV template")
    x.add_argument("--height", help="greyscale height/bump PNG on the template (white = raised); turned into normals")
    x.add_argument("--normal-strength", type=float)
    x.add_argument("--keep-slot", action="store_true")

    x = sp.add_parser("template")
    x.add_argument("targets", nargs="*")
    x.add_argument("--out")
    x.add_argument("--size", type=int, default=2048)

    x = sp.add_parser("build")
    x.add_argument("--out")
    x.add_argument("--animations")
    x.add_argument("--render", action="store_true")
    x.add_argument("--size", type=int, default=512)
    x.add_argument("--samples", type=int, default=12)

    x = sp.add_parser("render")
    x.add_argument("--views")
    x.add_argument("--focus", choices=["full", "upper", "head"])
    x.add_argument("--animation")
    x.add_argument("--frame", type=float, default=0.25, help="0..1 = fraction of the clip, >1 = frame number")
    x.add_argument("--size", type=int, default=512)
    x.add_argument("--samples", type=int, default=12)
    x.add_argument("--out")
    x.add_argument("--prefix")

    sp.add_parser("animations")
    x = sp.add_parser("reference-body")
    x.add_argument("--out", required=True)
    x.add_argument("--with-rig", action="store_true")

    x = sp.add_parser("autorig")
    x.add_argument("mesh")
    x.add_argument("--out", required=True)
    x.add_argument("--facing", default="auto", choices=["auto", "-y", "+y", "-x", "+x"])
    x.add_argument("--animations")
    x.add_argument("--render")
    x.add_argument("--method", default="auto", choices=["auto", "heat", "proximity"])

    x = sp.add_parser("validate")
    x.add_argument("glb")
    sp.add_parser("schema")
    return ap


COMMANDS = {
    "init": cmd_init, "show": cmd_show, "set": cmd_set, "catalog": cmd_catalog, "morphs": cmd_morphs,
    "skin": cmd_skin, "hair": cmd_hair, "garment": cmd_garment, "template": cmd_template, "build": cmd_build,
    "render": cmd_render, "animations": cmd_animations, "reference-body": cmd_reference_body,
    "autorig": cmd_autorig, "validate": cmd_validate, "schema": cmd_schema,
}


class _Parser(argparse.ArgumentParser):
    pass


def main(argv=None):
    ap = parser()
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        if e.code == 0:
            return 0
        return emit({"ok": False, "error": {"code": "bad_arguments", "message": "Invalid command line",
                                            "hint": "Run `ccreator schema` or `ccreator <command> --help`"}}, 2)
    try:
        if a.cmd == "hair" and a.action == "set" and not a.style:
            raise CliError("missing_arg", "hair set needs a style", hint=f"Valid: {', '.join(catalog.HAIR_STYLES)}")
        if a.cmd == "garment" and a.action in ("add",) and not a.type:
            raise CliError("missing_arg", "garment add needs a type", hint=f"Valid: {', '.join(catalog.GARMENTS)}")
        if a.cmd == "garment" and a.action in ("set", "remove") and not (a.type or a.id):
            raise CliError("missing_arg", f"garment {a.action} needs a garment id")
        res = COMMANDS[a.cmd](a)
        return emit({"ok": True, "command": a.cmd, **res})
    except CliError as e:
        return emit({"ok": False, "command": a.cmd, "error": e.to_dict()}, e.exit_code)
    except Exception as e:  # internal error: give the agent the traceback to debug with
        return emit({"ok": False, "command": a.cmd, "error": {
            "code": "internal", "message": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc().splitlines()[-12:],
            "hint": "Check build/blender.log in the project for Blender's own output"}}, 1)


if __name__ == "__main__":
    sys.exit(main())
