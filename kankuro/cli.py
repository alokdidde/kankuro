"""kankuro: a JSON-speaking character creator CLI for AI agents.

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

from . import appearance, catalog, morph, spec as specmod
from .errors import CliError

VERSION = "0.3.0"


def emit(obj, code=0):
    sys.stdout.write(json.dumps(obj, indent=None if os.environ.get("KANKURO_COMPACT") else 2, default=str) + "\n")
    sys.stdout.flush()
    return code


def _project(a):
    return os.path.abspath(a.project or os.environ.get("KANKURO_PROJECT") or ".")


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
        "fabrics": {k: v["desc"] for k, v in __import__("kankuro.fabric", fromlist=["FABRICS"]).FABRICS.items()},
        "materials": {"presets": __import__("kankuro.matlib", fromlist=["summary"]).summary(),
                      "regions": {"border": "band along every open edge (hems, neckline, cuffs, a saree's long "
                                            "edges), not the sewn seams",
                                  "hem": "band along the lowest open edges only",
                                  "<name> --mask PNG": "your own mask on the garment's UV template (white = in)"},
                      "usage": "kankuro garment set saree --material-region border=gold_zari  |  "
                               "kankuro garment import --file armour.glb --id kavach --material bronze"},
        "face_sliders": {k: {"range": r, "desc": d} for k, (d, _, r) in appearance.FACE_SLIDERS.items()},
        "face_presets": {k: v["desc"] for k, v in appearance.FACE_PRESETS.items()},
        "colors": {"skin": appearance.SKIN_TONES, "hair": appearance.HAIR_COLORS, "eyes": appearance.EYE_COLORS,
                   "usage": "any colour option takes #RRGGBB or one of these names"},
        "brows": {"keys": {k: {"default": d, "range": r, "desc": desc} for k, (d, r, desc) in appearance.BROW_KEYS.items()},
                  "presets": appearance.BROW_PRESETS},
        "detail_morphs": f"{len(morph.modifier_catalog())} modifiers; list with `kankuro morphs`",
        "animations": "list with `kankuro animations`",
        "expressions": {"blendshapes": __import__("kankuro.face", fromlist=["ARKIT_NAMES"]).ARKIT_NAMES,
                        "presets": list(__import__("kankuro.face", fromlist=["PRESETS"]).PRESETS),
                        "usage": "kankuro render --focus head --expression smile  (or jawOpen=0.6,eyeBlinkLeft=1)"},
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
            "usage": "kankuro set body.morphs.<name>=<value>  (e.g. body.morphs.nose/nose-scale-horiz-decr|incr=0.4)"}


def cmd_hair(a):
    p = _project(a)
    s = specmod.load(p)
    if a.action == "remove":
        s["hair"] = None
    elif a.action == "set":
        if not a.style and s["hair"] and a.color:
            if s["hair"].get("source") or s["hair"].get("style") == "custom":
                s["hair"]["color"] = specmod.color(a.color, "color", "hair")
                specmod.save(p, s)
                return {"hair": s["hair"]}
            a.style = s["hair"]["style"]
        if a.style not in catalog.HAIR_STYLES:
            raise CliError("unknown_hair", f"Unknown hair style '{a.style}'",
                           hint=f"Valid: {', '.join(catalog.HAIR_STYLES)}")
        h = {"style": a.style, "color": specmod.color(a.color, "color", "hair") or (s["hair"] or {}).get("color") or "#3b2a1e"}
        if a.texture:
            h["texture"] = specmod.import_file(p, a.texture, "textures")
        s["hair"] = h
    elif a.action == "import":
        if not a.file:
            raise CliError("missing_arg", "hair import needs --file <mesh>")
        h = {"style": "custom", "source": specmod.import_file(p, a.file, "meshes"),
             "color": specmod.color(a.color, "color", "hair")}
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
    _garment_material(p, g, a)
    specmod.save(p, s)
    out = {"garment": g, "garments": s["garments"]}
    if replaced:
        out["replaced"] = replaced
    return out


def _garment_material(p, g, a):
    """--material, --material-region NAME=PRESET[:#RRGGBB] and --mask PNG."""
    from . import matlib
    if a.material is not None:
        if a.material == "none":
            g.pop("material", None)
        else:
            matlib.check(a.material)
            g["material"] = a.material
            if a.color is None:
                g.pop("color", None)  # show the preset's own colour (gold, silver...) unless one is given
    regions = g.get("material_regions") or {}
    for item in a.material_region or []:
        name, sep, val = item.partition("=")
        if not sep or not name:
            raise CliError("bad_value", f"--material-region '{item}': expected NAME=PRESET",
                           hint="e.g. --material-region border=gold_zari (regions: border, hem, or any name with --mask)")
        if val == "none":
            regions.pop(name, None)
            continue
        preset, _, col = val.partition(":")
        matlib.check(preset, f"material_regions.{name}")
        ref = {"preset": preset}
        if col:
            ref["color"] = specmod.color(col, f"material_regions.{name}.color")
        if a.mask:
            ref["mask"] = specmod.import_file(p, a.mask, "textures")
        elif name not in matlib.REGIONS:
            raise CliError("missing_arg", f"Region '{name}' is not built in; pass --mask <png>",
                           hint="Built-in regions: " + ", ".join(matlib.REGIONS))
        regions[name] = ref["preset"] if len(ref) == 1 else ref
    if a.mask and not a.material_region:
        raise CliError("missing_arg", "--mask needs --material-region NAME=PRESET")
    if regions:
        g["material_regions"] = regions
    else:
        g.pop("material_regions", None)


def _vec3(x, name):
    try:
        v = [float(t) for t in x.split(",")]
    except ValueError:
        v = []
    if len(v) != 3:
        raise CliError("bad_value", f"--{name} expects three numbers x,y,z", hint=f"e.g. --{name} 0,0,0.02")
    return v


def _find(items, iid, kind, code):
    for x in items:
        if x["id"] == iid:
            return x
    raise CliError(code, f"No {kind} with id '{iid}'",
                   hint="Current ids: " + (", ".join(x["id"] for x in items) or "(none)"))


def _placement(p, x, a, builtins, kind):
    """Shared accessory/prop options: --file/--builtin, --offset/--rotate/--scale, --material/--color."""
    if getattr(a, "file", None):
        x["file"] = specmod.import_file(p, a.file, "meshes")
        x.pop("builtin", None)
    if getattr(a, "builtin", None):
        if a.builtin not in builtins:
            raise CliError(f"unknown_{kind}", f"Unknown built-in {kind} '{a.builtin}'", hint="Valid: " + ", ".join(builtins))
        x["builtin"] = a.builtin
        x.pop("file", None)
    if a.offset is not None:
        x["offset"] = _vec3(a.offset, "offset")
    if a.rotate is not None:
        x["rotate"] = _vec3(a.rotate, "rotate")
    if a.scale is not None:
        x["scale"] = a.scale
    if a.material is not None:
        from . import matlib
        if a.material == "none":
            x.pop("material", None)
        else:
            matlib.check(a.material)
            x["material"] = a.material
    if a.color is not None:
        x["color"] = specmod.color(a.color, "color") if a.color else None
    if a.roughness is not None:
        x["roughness"] = a.roughness


def cmd_accessory(a):
    p = _project(a)
    s = specmod.load(p)
    items = s.setdefault("accessories", [])
    if a.action == "list":
        return {"accessories": items, "builtins": {k: v["desc"] for k, v in catalog.ACCESSORIES.items()},
                "fits": list(catalog.ACCESSORY_FITS)}
    if not a.id:
        raise CliError("missing_arg", f"accessory {a.action} needs an id")
    if a.action == "remove":
        x = _find(items, a.id, "accessory", "no_accessory")
        items.remove(x)
        specmod.save(p, s)
        return {"removed": x["id"], "accessories": items}
    if a.action == "add":
        if any(x["id"] == a.id for x in items):
            raise CliError("duplicate_id", f"Accessory id '{a.id}' already exists", hint="Use `accessory set` to change it")
        x = {"id": a.id}
        if not a.file and not a.builtin:
            if a.id not in catalog.ACCESSORIES:
                raise CliError("missing_arg", "accessory add needs --file <mesh> or --builtin <name>",
                               hint="Built-ins: " + ", ".join(catalog.ACCESSORIES))
            a.builtin = a.id
        if a.builtin and a.builtin in catalog.ACCESSORIES:
            d = catalog.ACCESSORIES[a.builtin]
            x.update({k: d[k] for k in ("bone", "fit", "hang", "material") if k in d})
        items.append(x)
    else:
        x = _find(items, a.id, "accessory", "no_accessory")
    _placement(p, x, a, catalog.ACCESSORIES, "accessory")
    if a.bone is not None:
        x["bone"] = specmod.check_bone(a.bone, "--bone")
    if "bone" not in x:
        raise CliError("missing_arg", "accessory add needs --bone <bone>",
                       hint="Any Mesh2Motion bone, e.g. head, neck_01, spine_03, upperarm_l, lowerarm_r")
    if a.fit is not None:
        x["fit"] = a.fit
    if a.hang is not None:
        x["hang"] = a.hang
    if a.layer is not None:
        x["layer"] = a.layer
    if a.hide_hair is not None:
        x["hide_hair"] = a.hide_hair == "true"
    specmod.validate(s, p)
    specmod.save(p, s)
    return {"accessory": x, "accessories": items}


def cmd_prop(a):
    p = _project(a)
    s = specmod.load(p)
    items = s.setdefault("props", [])
    if a.action == "list":
        return {"props": items, "builtins": {k: v["desc"] for k, v in catalog.PROPS.items()},
                "grips": {k: v["desc"] for k, v in catalog.GRIPS.items()}}
    if not a.id:
        raise CliError("missing_arg", f"prop {a.action} needs an id")
    if a.action == "remove":
        x = _find(items, a.id, "prop", "no_prop")
        items.remove(x)
        specmod.save(p, s)
        return {"removed": x["id"], "props": items}
    if a.action == "add":
        if any(x["id"] == a.id for x in items):
            raise CliError("duplicate_id", f"Prop id '{a.id}' already exists", hint="Use `prop set` to change it")
        x = {"id": a.id}
        if not a.file and not a.builtin:
            if a.id not in catalog.PROPS:
                raise CliError("missing_arg", "prop add needs --file <mesh> or --builtin <name>",
                               hint="Built-ins: " + ", ".join(catalog.PROPS))
            a.builtin = a.id
        if a.builtin and a.builtin in catalog.PROPS:
            d = catalog.PROPS[a.builtin]
            x.update({k: d[k] for k in ("hand", "grip", "anchor", "material", "color") if k in d})
        x.setdefault("hand", "r")
        x.setdefault("grip", "power")
        items.append(x)
    else:
        x = _find(items, a.id, "prop", "no_prop")
    _placement(p, x, a, catalog.PROPS, "prop")
    if a.hand is not None:
        x["hand"] = a.hand
    if a.anchor is not None:
        x["anchor"] = a.anchor
    if a.grip is not None:
        x["grip"] = a.grip
    if a.grip_weight is not None:
        x["grip_weight"] = max(0.0, min(1.0, a.grip_weight))
    if a.reach is not None:
        x["reach"] = a.reach
    if x["hand"] == "both":
        x.setdefault("anchor", "r")
    specmod.validate(s, p)
    specmod.save(p, s)
    return {"prop": x, "props": items}


def cmd_grip(a):
    return {"grips": {k: {kk: vv for kk, vv in v.items()} for k, v in catalog.GRIPS.items()}}


def cmd_bones(a):
    p = _project(a)
    s = specmod.load(p)
    items = s.setdefault("extra_bones", [])
    if a.action == "list":
        out = []
        for c in items:
            out.append({**c, "bones": [f"{c['id']}_{k + 1:02d}" for k in range(c.get("count", 6))]})
        sockets = sorted({f"prop_{pr['anchor'] if pr.get('hand') == 'both' else pr.get('hand')}" for pr in s.get("props") or []})
        hangs = [f"{x['id']}_{k + 1:02d}" for x in s.get("accessories") or [] for k in range(x.get("hang", 0))]
        return {"extra_bones": out, "prop_sockets": sockets, "accessory_hang_bones": hangs}
    if not a.id:
        raise CliError("missing_arg", f"bones {a.action} needs an id")
    if a.action == "remove":
        x = _find(items, a.id, "bone chain", "no_chain")
        items.remove(x)
        specmod.save(p, s)
        return {"removed": x["id"], "extra_bones": items}
    if a.action == "add":
        if any(x["id"] == a.id for x in items):
            raise CliError("duplicate_id", f"Chain id '{a.id}' already exists", hint="Remove it first, or pick another id")
        if not a.parent:
            raise CliError("missing_arg", "bones add needs --parent <bone>", hint="e.g. --parent pelvis (a tail), head (a braid)")
        x = {"id": a.id, "parent": a.parent, "count": 6, "length": 0.6, "taper": 0.5, "secondary_motion": {}}
        items.append(x)
    else:
        x = _find(items, a.id, "bone chain", "no_chain")
    if a.parent is not None:
        x["parent"] = a.parent
    for k in ("count", "length", "taper", "radius"):
        if getattr(a, k) is not None:
            x[k] = getattr(a, k)
    if a.curve is not None:
        d, _, v = a.curve.partition(":")
        if d not in ("up", "down") or not v:
            raise CliError("bad_value", "--curve expects up:F or down:F", hint="e.g. --curve up:0.3")
        x["curve"] = {d: float(v)}
    if a.follow is not None:
        x["follow"] = a.follow if a.follow != "none" else None
        if x["follow"] is None:
            x.pop("follow")
    if a.color is not None:
        x["color"] = specmod.color(a.color, "color")
    if a.material is not None:
        x["material"] = a.material
    if a.no_motion:
        x["secondary_motion"] = False
    for k in ("stiffness", "damping", "gravity"):
        if getattr(a, k) is not None:
            if not isinstance(x.get("secondary_motion"), dict):
                x["secondary_motion"] = {}
            x["secondary_motion"][k] = getattr(a, k)
    specmod.validate(s, p)
    specmod.save(p, s)
    return {"chain": x, "bones": [f"{x['id']}_{k + 1:02d}" for k in range(x.get("count", 6))], "extra_bones": items}


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
        clips = build.export_glb(b, out_path, anims, _secondary(a))
    manifest = {
        "glb": out_path, "bytes": os.path.getsize(out_path), "animations": clips,
        "seconds": round(time.time() - t0, 2), "timings": b.timings, **info,
        "hidden_body_faces": getattr(b, "hidden_faces", 0), "warnings": b.warnings,
    }
    if renders:
        manifest["renders"] = renders
    json.dump(manifest, open(os.path.join(p, "build", "manifest.json"), "w"), indent=2)
    return manifest


def _secondary(a):
    """--secondary-motion all (default) | none | chain ids."""
    v = getattr(a, "secondary_motion", None)
    if not v or v == "all":
        return None
    return [] if v == "none" else _parse_list(v)


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
    expr = None
    if a.expression:
        from . import face
        expr, bad_name = face.parse_expression(a.expression)
        if expr is None:
            raise CliError("bad_expression", f"Unknown expression or blendshape '{bad_name}'",
                           hint=f"Presets: {', '.join(face.PRESETS)}; or ARKit names with weights, e.g. "
                                "jawOpen=0.6,mouthSmileLeft=1 (list them with `kankuro catalog expressions`)")
        if s.get("face", {}).get("blendshapes", "arkit52") == "none":
            raise CliError("no_blendshapes", "This character is built without facial blendshapes",
                           hint="kankuro set face.blendshapes=arkit52")
    with util.quiet(_log(p)):
        b = build.build_scene(s, p, work)
        if expr:
            build.set_expression(b, expr)
        frame = None
        if a.animation:
            frame = build.pose_clip(b, a.animation, a.frame, _secondary(a))
        if s.get("props"):
            from .blender import props
            if not a.animation:
                props.pose_grips(b)
            b.warnings += props.penetration(b)
        bbox = _focus_bbox(b, a.focus)
        prefix = a.prefix or ("pose_" + a.animation if a.animation else "render")
        paths, sheet = render.render_views(b.meshes, os.path.abspath(a.out or os.path.join(p, "renders")),
                                           views=views, size=a.size, samples=a.samples, prefix=prefix, bbox=bbox)
    return {"views": dict(zip(views, paths)), "sheet": sheet, "animation": a.animation, "frame": frame,
            "focus": a.focus or "full", **({"expression": expr} if expr else {}),
            **({"warnings": b.warnings} if b.warnings else {}),
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
                textures.uv_template(garments.uv_polygons(m), path, f"kankuro {gid} UV template ({info['layout']})",
                                     size=a.size, mask_out=mask, labels=info["labels"], divider=False)
            else:
                textures.uv_template(garments.uv_polygons(m), path, f"kankuro {gid} UV template - left: front view, right: back view (seen from behind)",
                                     size=a.size, mask_out=mask)
            results[gid] = {"template": path, "mask": mask, "layout": info.get("layout", "front_back_flat_sketch"),
                            "size": a.size}
            if info.get("scale_px_per_m"):  # the built-in material regions (for --material-region)
                from PIL import Image
                width = catalog.GARMENTS.get(gid, {}).get("border", 0.025)
                for rname in ("border", "hem"):
                    rm = build.region_mask(m, rname, a.size, info["scale_px_per_m"], width)
                    rp = os.path.join(out_dir, f"{gid}_{rname}_mask.png")
                    Image.fromarray((rm * 255).astype("uint8")).save(rp)
                    results[gid][f"{rname}_mask"] = rp
    if "body" in want_types:
        from . import morph as mm
        import numpy as np
        faces, fuvs = mm.faces_of_group("body")
        uvs = mm.base()["uvs"]
        polys = [[tuple(uvs[i]) for i in fu] for fu in fuvs]
        path = os.path.join(out_dir, "body_template.png")
        mask = os.path.join(out_dir, "body_mask.png")
        textures.uv_template(polys, path, "kankuro body skin UV template (MakeHuman UV layout)", size=a.size,
                             labels=(), mask_out=mask)
        results["body"] = {"template": path, "mask": mask, "layout": "makehuman_body"}
    return {"templates": results,
            "how_to_retexture": "Paint/generate a same-size image over the template (keep the garment inside the "
                                "grey area; the mask is white where pixels are used), then run "
                                "`kankuro garment set <id> --texture <png>` (or `kankuro set skin.texture` via "
                                "`kankuro skin --texture <png>` for the body)."}


def cmd_skin(a):
    p = _project(a)
    s = specmod.load(p)
    if a.color:
        s["skin"]["color"] = specmod.color(a.color, "color", "skin")
    if a.texture is not None:
        s["skin"]["texture"] = specmod.import_file(p, a.texture, "textures") if a.texture else None
    if a.brow_color:
        s["skin"]["brow_color"] = specmod.color(a.brow_color, "brow_color", "hair")
    if a.detail is not None:
        s["skin"]["detail"] = a.detail == "true"
    specmod.save(p, s)
    out = {"skin": s["skin"]}
    if s["skin"].get("texture"):
        out["note"] = "A skin texture is set, so skin.color is ignored; pass --texture '' to use the colour"
    return out


def _assignments(items, prefix=""):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise CliError("bad_assignment", f"Expected slider=value, got '{item}'",
                           hint="e.g. nose.width=0.4 eyes.tilt=-0.3 (see `kankuro face list`)")
        k, v = item.split("=", 1)
        k = k.strip()
        if prefix and not k.startswith(prefix):
            k = prefix + k
        out[k] = specmod.parse_value(v)
    return out


def _face_summary(s):
    shape = s.get("face", {}).get("shape") or {}
    return {"shape": dict(sorted(shape.items())), "count": len(shape)}


def cmd_face(a):
    if a.action == "list":
        sliders = {k: {"range": r, "desc": d} for k, (d, _, r) in appearance.FACE_SLIDERS.items()
                   if not a.group or k.split(".")[0] == a.group}
        out = {"sliders": sliders, "groups": sorted({k.split(".")[0] for k in appearance.FACE_SLIDERS}),
               "presets": {k: v["desc"] for k, v in appearance.FACE_PRESETS.items()},
               "usage": "kankuro face set nose.width=0.4 jaw.width=-0.3 | face preset angular | "
                        "face randomize --seed 7 --strength 0.6 | face reset"}
        try:
            out["current"] = _face_summary(specmod.load(_project(a)))["shape"]
        except CliError:
            pass
        return out
    p = _project(a)
    s = specmod.load(p)
    face = s.setdefault("face", {"blendshapes": "arkit52"})
    shape = dict(face.get("shape") or {})
    if a.action == "set":
        vals = _assignments(a.values)
        if not vals:
            raise CliError("missing_arg", "face set needs slider=value pairs", hint="e.g. face set nose.width=0.4")
        for k, v in vals.items():
            if v is None or v == 0:
                appearance.clamp(k, 0)
                shape.pop(k, None)
            else:
                shape[k] = appearance.clamp(k, v)
    elif a.action == "preset":
        if not a.values:
            raise CliError("missing_arg", "face preset needs a name", hint=f"Valid: {', '.join(appearance.FACE_PRESETS)}")
        new = {}
        for name in a.values:
            for k, v in appearance.preset_shape(name, a.amount).items():
                new[k] = new.get(k, 0) + v
        shape = _merge(shape, new, a.add)
    elif a.action == "randomize":
        groups = _parse_list(a.groups)
        bad = [g for g in groups or [] if g not in {k.split(".")[0] for k in appearance.FACE_SLIDERS}]
        if bad:
            raise CliError("bad_group", f"Unknown face group(s): {', '.join(bad)}",
                           hint="Groups: " + ", ".join(sorted({k.split('.')[0] for k in appearance.FACE_SLIDERS})))
        if not 0 <= a.strength <= 1:
            raise CliError("bad_value", "--strength must be 0..1", hint="0.3 subtle, 0.5 natural, 1 extreme")
        seed = a.seed if a.seed is not None else int.from_bytes(os.urandom(3), "big")
        new = appearance.random_shape(seed, a.strength, groups)
        if groups and not a.add:
            shape = {k: v for k, v in shape.items() if k.split(".")[0] not in groups}
            a.add = True
        shape = _merge(shape, new, a.add)
        face["seed"] = seed
    elif a.action == "reset":
        groups = _parse_list(a.groups)
        shape = {k: v for k, v in shape.items() if groups and k.split(".")[0] not in groups}
    face["shape"] = shape
    specmod.save(p, s)
    out = _face_summary(s)
    if a.action == "randomize":
        out["seed"] = face["seed"]
    out["tip"] = "Check it with `kankuro render --focus head --views front,three_quarter,side`"
    return out


def _merge(shape, new, add):
    if not add:
        return new
    out = dict(shape)
    for k, v in new.items():
        out[k] = appearance.clamp(k, out.get(k, 0) + v)
    return {k: v for k, v in out.items() if abs(v) > 1e-4}


def cmd_eyes(a):
    p = _project(a)
    s = specmod.load(p)
    if a.color:
        s["eyes"]["iris_color"] = specmod.color(a.color, "color", "eyes")
    shape = s.setdefault("face", {}).setdefault("shape", {})
    for k, v in _assignments(a.values, "eyes.").items():
        if v is None or v == 0:
            appearance.clamp(k, 0)
            shape.pop(k, None)
        else:
            shape[k] = appearance.clamp(k, v)
    specmod.save(p, s)
    return {"eyes": s["eyes"], "shape": {k: v for k, v in sorted(shape.items()) if k.startswith("eyes.")},
            "sliders": {k: d for k, (d, _, _) in appearance.FACE_SLIDERS.items() if k.startswith("eyes.")}}


def cmd_brows(a):
    p = _project(a)
    s = specmod.load(p)
    sk = s["skin"]
    if a.preset:
        if a.preset not in appearance.BROW_PRESETS:
            raise CliError("unknown_brow_preset", f"Unknown eyebrow preset '{a.preset}'",
                           hint=f"Valid: {', '.join(appearance.BROW_PRESETS)}")
        sk.update(appearance.BROW_PRESETS[a.preset])
    for key in appearance.BROW_KEYS:
        v = getattr(a, key[len("brow_"):])
        if v is not None:
            sk[key] = appearance.check_brow(key, v)
    if a.color:
        sk["brow_color"] = None if a.color in ("hair", "none") else specmod.color(a.color, "color", "hair")
    if a.off or a.on:
        sk["brows"] = bool(a.on)
    shape = s.setdefault("face", {}).setdefault("shape", {})
    for k, v in _assignments(a.values, "brows.").items():
        if v is None or v == 0:
            appearance.clamp(k, 0)
            shape.pop(k, None)
        else:
            shape[k] = appearance.clamp(k, v)
    specmod.save(p, s)
    return {"brows": {k: sk.get(k, appearance.BROW_KEYS[k][0] if k in appearance.BROW_KEYS else None)
                      for k in ["brows", "brow_color", *appearance.BROW_KEYS]},
            "brow_color_used": sk.get("brow_color") or (s.get("hair") or {}).get("color"),
            "ridge_shape": {k: v for k, v in sorted(shape.items()) if k.startswith("brows.")},
            "presets": list(appearance.BROW_PRESETS)}


def cmd_animations(a):
    _bpy()
    from .blender import anim, util
    with util.quiet():
        util.reset_scene()
        clips = anim.list_clips()
    return {"library": "Mesh2Motion human-base (CC0)", "count": len(clips), "clips": clips,
            "usage": "kankuro build --animations Idle_A,Jog   (or --animations all)"}


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
                             "garments or hair on top of it, export as GLB/OBJ, then `kankuro garment import` / "
                             "`kankuro hair import`; they are conformed and skinned to any body shape."}


def cmd_autorig(a):
    _bpy()
    from .blender import autorig, util
    src = os.path.abspath(a.mesh)
    if not os.path.isfile(src):
        raise CliError("missing_file", f"File not found: {src}")
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    log = os.path.join(os.path.dirname(out), "autorig.log")
    props = []
    for k, item in enumerate(a.prop or []):
        name, _, rest = item.partition(":")
        hand, _, grip = rest.partition(":")
        pr = {"id": f"prop{k + 1}" if name not in catalog.PROPS else name}
        if name in catalog.PROPS:
            d = catalog.PROPS[name]
            pr.update(builtin=name, **{x: d[x] for x in ("hand", "grip", "anchor", "material", "color") if x in d})
        elif os.path.isfile(name):
            pr.update(file=os.path.abspath(name), hand="r", grip="power")
        else:
            raise CliError("unknown_prop", f"--prop {item}: not a built-in prop or a mesh file",
                           hint="Built-ins: " + ", ".join(catalog.PROPS) + "; or a path to a .glb/.obj/.fbx")
        if hand:
            pr["hand"] = hand
        if grip:
            if grip not in catalog.GRIPS:
                raise CliError("unknown_grip", f"Unknown grip '{grip}'", hint="Valid: " + ", ".join(catalog.GRIPS))
            pr["grip"] = grip
        if pr["hand"] == "both":
            pr.setdefault("anchor", "r")
        props.append(pr)
    chains = []
    for item in a.extra_chain or []:
        cid, _, rest = item.partition(":")
        part, _, n = rest.partition(":")
        if not cid or not part:
            raise CliError("bad_value", f"--extra-chain {item}: expected ID:PART[:COUNT]",
                           hint="PART is a mesh object or vertex group in the file, e.g. tail:Tail:8")
        specmod.check_id(cid, "--extra-chain")
        chains.append((cid, part, int(n) if n else 6))
    with util.quiet(log):
        r = autorig.run(src, out, facing=a.facing, animations=_parse_list(a.animations),
                        render_dir=os.path.abspath(a.render) if a.render else None, method=a.method,
                        props=props, chains=chains)
    return r


def cmd_validate(a):
    _bpy()
    from .blender import validate, util
    with util.quiet():
        r = validate.check(os.path.abspath(a.glb))
    return r


GUIDES = {
    "agents": ("agents.md", "driving kankuro from an AI agent: JSON contract, working loop, system prompt"),
    "start": ("getting-started.md", "ten-minute walk-through: body, face, hair, clothes, textures, GLB"),
    "cli": ("cli-reference.md", "every command, option, output and error code"),
    "spec": ("character-spec.md", "the character.json format"),
    "textures": ("codex-textures.md", "image-model prompts and file specs for garment textures"),
    "install": ("installation.md", "installing, platforms, troubleshooting"),
}


def _guide_text(topic):
    if topic not in GUIDES:
        raise CliError("unknown_topic", f"Unknown guide topic '{topic}'", hint=f"Valid: {', '.join(GUIDES)}")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guides", GUIDES[topic][0])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    others = ", ".join(t for t in GUIDES if t != topic)
    return text.rstrip() + f"\n\n---\nMore: `kankuro guide <topic>` ({others}), `kankuro <command> --help`.\n"


def cmd_guide(a):
    if a.list:
        return {"topics": {k: v[1] for k, v in GUIDES.items()}, "usage": "kankuro guide <topic>"}
    return {"topic": a.topic, "text": _guide_text(a.topic)}


def cmd_schema(a):
    return {"version": VERSION, "commands": SCHEMA, "spec_file": specmod.SPEC_FILE,
            "conventions": {
                "units": "metres; feet on the ground at z=0",
                "facing": "-Y in Blender, +Z in glTF",
                "rest_pose": "T-pose matching Mesh2Motion rig-human",
                "skeleton": "Mesh2Motion human: 65 bones, Unreal-style names (pelvis, spine_01..03, clavicle_l, ...)",
                "output": "one JSON object per command on stdout",
            },
            "learn_more": "kankuro guide (agent guide, plain text), kankuro guide --list, kankuro <command> --help"}


SCHEMA = {
    "init <dir> [--preset P] [--name N] [--force]": "create a project with character.json",
    "show": "print the spec and last build manifest",
    "set <path>=<value> ...": "edit the spec: body.macros.<slider>, body.morphs.<modifier>, face.shape.<slider>, body.height_cm, skin.*, eyes.iris_color, name",
    "catalog [section]": "presets, body sliders, hair styles, garment types",
    "morphs [--group G] [--search S]": "list the detailed morph modifiers (face, torso, limbs...)",
    "skin [--color HEX|NAME] [--texture PNG|''] [--brow-color HEX|NAME]": "whole-body skin tone (names: `catalog colors`) or a painted skin texture (body UV template)",
    "face list [--group G]": "face shape sliders (head, forehead, brows, eyes, nose, mouth, jaw, chin, cheeks, ears, neck), presets, current values",
    "face set <slider>=<value> ...": "set face sliders, e.g. nose.width=0.4 jaw.width=-0.3 (bipolar -1..1, head shapes 0..1; 0 removes)",
    "face preset <name...> [--amount F] [--add]": "apply a face archetype (angular, soft, round, long, heart, square, delicate, rugged, aquiline, broad)",
    "face randomize [--seed N] [--strength 0..1] [--groups nose,eyes] [--add]": "random plausible face; same seed = same face",
    "face reset [--groups G,...]": "clear face sliders (all, or only some groups)",
    "eyes [--color HEX|NAME] [size=.. tilt=.. openness=.. spacing=.. monolid=.. ...]": "iris colour and eye shape (the eyes.* face sliders)",
    "brows [--preset P] [--color HEX|NAME|hair] [--thickness F] [--arch F] [--density F] [--length F] [--on|--off] [height=.. tilt=.. ridge=..]": "eyebrow hair shape and colour, and the brow ridge sliders",
    "hair set [style] [--color HEX|NAME] [--texture PNG]": "procedural hair style; with only --color, recolours the current hair",
    "hair import --file MESH [--color HEX] [--texture PNG]": "custom hair mesh authored on the reference body",
    "hair remove": "bald",
    "garment add <type> [--id ID] [--color HEX] [--texture PNG] [--layer N] [--keep-slot]": "add a standard garment (replaces others in its slot unless --keep-slot)",
    "garment import --file MESH --id ID [--texture PNG] [--color HEX]": "custom garment authored on the reference body",
    "garment set <id> [--color HEX] [--texture PNG|''] [--fabric NAME|none] [--normal PNG] [--height PNG] [--normal-strength F] [--layer N] [--hide-body true|false]": "change a garment; texture = albedo, height/normal add 3D relief on the same UV template",
    "garment set <id> [--material PRESET|none] [--material-region NAME=PRESET[:#HEX]] [--mask PNG]": "metal/gem/zari materials for the whole garment or a region of its UV template (`catalog materials`)",
    "garment remove <id>": "remove a garment",
    "accessory add|set <id> [--file MESH|--builtin NAME] [--bone BONE] [--fit none|wrap|chest|neck|pierce] [--hang N] [--offset X,Y,Z] [--rotate X,Y,Z] [--scale S] [--material PRESET]": "rigid jewellery/armour on one bone, carried onto every body shape",
    "accessory remove <id> | accessory list": "remove or list accessories and the built-ins",
    "prop add|set <id> [--file MESH|--builtin NAME] [--hand l|r|both] [--anchor l|r] [--grip GRIP] [--reach M] [--offset X,Y,Z] [--rotate X,Y,Z]": "an object in the hand on a prop_l/prop_r socket bone, with a grip pose baked over every clip",
    "prop remove <id> | prop list | grip list": "remove or list props; list the grips",
    "bones add|set <id> --parent BONE [--count N] [--length M] [--taper T] [--curve up:F|down:F] [--radius R] [--follow hair] [--stiffness K] [--damping D] [--gravity G] [--no-motion]": "extra bone chain (tail, braid) under a standard bone, with follow-through on clips",
    "bones remove <id> | bones list": "remove or list extra bone chains",
    "template [targets...] [--out DIR] [--size PX]": "write UV template + mask PNGs (garment ids/types, 'body', or 'all')",
    "build [--out GLB] [--animations A,B|all] [--render] [--secondary-motion all|none|IDS]": "build and export the rigged GLB",
    "render [--views front,three_quarter,side,back] [--focus full|upper|head] [--animation CLIP --frame 0..1] [--expression smile|jawOpen=0.6,...] [--secondary-motion all|none|IDS]": "preview PNGs",
    "animations": "list Mesh2Motion clips that can be baked into the GLB",
    "reference-body --out GLB [--with-rig]": "neutral body for authoring custom garments/hair",
    "autorig <mesh> --out GLB [--facing auto|-y|+y|-x|+x] [--animations A,B] [--render DIR] [--prop NAME[:HAND[:GRIP]]] [--extra-chain ID:PART[:COUNT]]": "rig any humanoid mesh to the Mesh2Motion skeleton",
    "validate <glb>": "check a GLB against the Mesh2Motion human standard",
    "schema": "this description",
    "guide [topic] [--list] [--json]": "print a usage guide as plain text (default: the agent guide)",
}


def parser():
    from . import helptext
    names = helptext.names()
    ap = argparse.ArgumentParser(prog="kankuro", description=helptext.TOP_DESCRIPTION,
                                 epilog=helptext.TOP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--project", help="project directory (default: $KANKURO_PROJECT or cwd)")
    ap.add_argument("--version", action="version", version=VERSION)
    sp = ap.add_subparsers(dest="cmd", required=True, metavar="<command>")

    def _sub(name):
        h = helptext.COMMANDS[name]
        return sp.add_parser(name, help=h["summary"], description=h["description"],
                             epilog="examples:\n" + helptext.fill(h["examples"], names),
                             formatter_class=argparse.RawDescriptionHelpFormatter)

    x = _sub("init")
    x.add_argument("dir")
    x.add_argument("--preset", default="neutral")
    x.add_argument("--name")
    x.add_argument("--force", action="store_true")
    _sub("show")
    x = _sub("set")
    x.add_argument("assignments", nargs="+")
    x = _sub("catalog")
    x.add_argument("section", nargs="?")
    x = _sub("morphs")
    x.add_argument("--group")
    x.add_argument("--search")
    x = _sub("skin")
    x.add_argument("--color")
    x.add_argument("--texture")
    x.add_argument("--brow-color")
    x.add_argument("--detail", choices=["true", "false"])

    x = _sub("face")
    x.add_argument("action", choices=["list", "set", "preset", "randomize", "reset"])
    x.add_argument("values", nargs="*")
    x.add_argument("--group")
    x.add_argument("--groups")
    x.add_argument("--seed", type=int)
    x.add_argument("--strength", type=float, default=0.5)
    x.add_argument("--amount", type=float, default=1.0)
    x.add_argument("--add", action="store_true", help="add to the current sliders instead of replacing them")
    x = _sub("eyes")
    x.add_argument("values", nargs="*")
    x.add_argument("--color")
    x = _sub("brows")
    x.add_argument("values", nargs="*")
    x.add_argument("--preset")
    x.add_argument("--color")
    for k in ("thickness", "arch", "density", "length"):
        x.add_argument("--" + k, type=float)
    x.add_argument("--on", action="store_true")
    x.add_argument("--off", action="store_true")

    x = _sub("hair")
    x.add_argument("action", choices=["set", "import", "remove"])
    x.add_argument("style", nargs="?")
    x.add_argument("--color")
    x.add_argument("--texture")
    x.add_argument("--file")

    x = _sub("garment")
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
    x.add_argument("--material", help="material preset for the whole garment (see `catalog materials`) or 'none'")
    x.add_argument("--material-region", action="append", metavar="NAME=PRESET[:#RRGGBB]",
                   help="a region of the UV template in another material, e.g. border=gold_zari; PRESET none removes it")
    x.add_argument("--mask", help="greyscale PNG on the garment UV template (white = in the region) for --material-region")
    x.add_argument("--keep-slot", action="store_true")

    def _place(x):
        x.add_argument("--file", help="mesh (.glb/.gltf/.obj/.fbx) modelled on `kankuro reference-body`")
        x.add_argument("--builtin")
        x.add_argument("--offset", metavar="X,Y,Z")
        x.add_argument("--rotate", metavar="X,Y,Z")
        x.add_argument("--scale", type=float)
        x.add_argument("--material")
        x.add_argument("--color")
        x.add_argument("--roughness", type=float)

    x = _sub("accessory")
    x.add_argument("action", choices=["add", "set", "remove", "list"])
    x.add_argument("id", nargs="?")
    _place(x)
    x.add_argument("--bone")
    x.add_argument("--fit", choices=list(catalog.ACCESSORY_FITS))
    x.add_argument("--hang", type=int)
    x.add_argument("--layer", type=int)
    x.add_argument("--hide-hair", choices=["true", "false"])

    x = _sub("prop")
    x.add_argument("action", choices=["add", "set", "remove", "list"])
    x.add_argument("id", nargs="?")
    _place(x)
    x.add_argument("--hand", choices=["l", "r", "both"])
    x.add_argument("--anchor", choices=["l", "r"])
    x.add_argument("--grip", choices=list(catalog.GRIPS))
    x.add_argument("--grip-weight", type=float)
    x.add_argument("--reach", type=float)

    x = _sub("grip")
    x.add_argument("action", choices=["list"])

    x = _sub("bones")
    x.add_argument("action", choices=["add", "set", "remove", "list"])
    x.add_argument("id", nargs="?")
    x.add_argument("--parent")
    x.add_argument("--count", type=int)
    x.add_argument("--length", type=float)
    x.add_argument("--taper", type=float)
    x.add_argument("--curve", metavar="up:F|down:F")
    x.add_argument("--radius", type=float)
    x.add_argument("--color")
    x.add_argument("--material")
    x.add_argument("--follow", choices=["hair", "none"])
    x.add_argument("--stiffness", type=float)
    x.add_argument("--damping", type=float)
    x.add_argument("--gravity", type=float)
    x.add_argument("--no-motion", action="store_true")

    x = _sub("template")
    x.add_argument("targets", nargs="*")
    x.add_argument("--out")
    x.add_argument("--size", type=int, default=2048)

    x = _sub("build")
    x.add_argument("--out")
    x.add_argument("--animations")
    x.add_argument("--render", action="store_true")
    x.add_argument("--size", type=int, default=512)
    x.add_argument("--samples", type=int, default=12)
    x.add_argument("--secondary-motion", metavar="all|none|IDS",
                   help="extra bone chains to bake follow-through for (default all)")

    x = _sub("render")
    x.add_argument("--views")
    x.add_argument("--focus", choices=["full", "upper", "head"])
    x.add_argument("--animation")
    x.add_argument("--frame", type=float, default=0.25, help="0..1 = fraction of the clip, >1 = frame number")
    x.add_argument("--expression", help="facial expression: a preset (smile, surprise, ...) and/or ARKit weights")
    x.add_argument("--size", type=int, default=512)
    x.add_argument("--samples", type=int, default=12)
    x.add_argument("--out")
    x.add_argument("--prefix")
    x.add_argument("--secondary-motion", metavar="all|none|IDS")

    _sub("animations")
    x = _sub("reference-body")
    x.add_argument("--out", required=True)
    x.add_argument("--with-rig", action="store_true")

    x = _sub("autorig")
    x.add_argument("mesh")
    x.add_argument("--out", required=True)
    x.add_argument("--facing", default="auto", choices=["auto", "-y", "+y", "-x", "+x"])
    x.add_argument("--animations")
    x.add_argument("--render")
    x.add_argument("--method", default="auto", choices=["auto", "heat", "proximity"])
    x.add_argument("--prop", action="append", metavar="NAME[:HAND[:GRIP]]")
    x.add_argument("--extra-chain", action="append", metavar="ID:PART[:COUNT]")

    x = _sub("validate")
    x.add_argument("glb")
    _sub("schema")
    x = _sub("guide")
    x.add_argument("topic", nargs="?", default="agents")
    x.add_argument("--list", action="store_true")
    x.add_argument("--json", action="store_true")

    # Fill in per-option help from helptext (kept there so the parser stays compact).
    for name, sub in sp.choices.items():
        args = helptext.COMMANDS.get(name, {}).get("args", {})
        for act in sub._actions:
            if act.dest in args:
                act.help = helptext.fill(args[act.dest], names).replace("%", "%%")
    return ap


COMMANDS = {
    "init": cmd_init, "show": cmd_show, "set": cmd_set, "catalog": cmd_catalog, "morphs": cmd_morphs,
    "skin": cmd_skin, "face": cmd_face, "eyes": cmd_eyes, "brows": cmd_brows, "hair": cmd_hair, "garment": cmd_garment, "template": cmd_template, "build": cmd_build,
    "render": cmd_render, "animations": cmd_animations, "reference-body": cmd_reference_body,
    "autorig": cmd_autorig, "validate": cmd_validate, "schema": cmd_schema, "guide": cmd_guide,
    "accessory": cmd_accessory, "prop": cmd_prop, "grip": cmd_grip, "bones": cmd_bones,
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
                                            "hint": "Run `kankuro --help`, `kankuro <command> --help` or `kankuro guide`"}}, 2)
    try:
        if a.cmd == "hair" and a.action == "set" and not a.style and not a.color:
            raise CliError("missing_arg", "hair set needs a style", hint=f"Valid: {', '.join(catalog.HAIR_STYLES)}")
        if a.cmd == "garment" and a.action in ("add",) and not a.type:
            raise CliError("missing_arg", "garment add needs a type", hint=f"Valid: {', '.join(catalog.GARMENTS)}")
        if a.cmd == "garment" and a.action in ("set", "remove") and not (a.type or a.id):
            raise CliError("missing_arg", f"garment {a.action} needs a garment id")
        if a.cmd == "guide" and not (a.json or a.list):  # plain text for reading, not JSON
            sys.stdout.write(_guide_text(a.topic))
            return 0
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
