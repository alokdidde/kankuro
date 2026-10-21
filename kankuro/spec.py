"""The character spec (character.json): a small declarative document the CLI edits and `build` renders."""
import copy
import json
import os
import re
import shutil

from . import appearance, catalog, matlib, morph
from .errors import CliError

SPEC_FILE = "character.json"
VERSION = 1

PRESETS = {
    "neutral": {},
    "female": {"gender": 0.0, "breast_size": 0.55},
    "male": {"gender": 1.0, "muscle": 0.55},
    "athletic_female": {"gender": 0.0, "muscle": 0.75, "weight": 0.4, "proportions": 0.8},
    "athletic_male": {"gender": 1.0, "muscle": 0.85, "weight": 0.45, "proportions": 0.8},
    "heavy_male": {"gender": 1.0, "weight": 0.9, "muscle": 0.4},
    "child": {"age": 0.15},
    "elder_female": {"gender": 0.0, "age": 0.95, "weight": 0.55},
    "elder_male": {"gender": 1.0, "age": 0.95, "weight": 0.55},
}

HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


def default_spec(name="character", preset="neutral"):
    if preset not in PRESETS:
        raise CliError("unknown_preset", f"Unknown preset '{preset}'", hint=f"Valid: {', '.join(PRESETS)}")
    return {
        "version": VERSION,
        "name": name,
        "body": {"preset": preset, "macros": dict(PRESETS[preset]), "morphs": {}, "height_cm": None},
        "skin": {"color": "#d8a383", "texture": None, "roughness": 0.6,
                 "lips": True, "brows": True, "detail": True, "brow_color": None,
                 **{k: d for k, (d, _, _) in appearance.BROW_KEYS.items()}},
        "eyes": {"iris_color": None},
        "face": {"blendshapes": "arkit52", "shape": {}},
        "hair": None,
        "garments": [],
        "export": {"animations": [], "hide_body_under_clothes": True, "texture_size": 2048},
    }


def project_path(project):
    return os.path.join(project, SPEC_FILE)


def load(project):
    p = project_path(project)
    if not os.path.exists(p):
        raise CliError("no_project", f"No {SPEC_FILE} in '{project}'",
                       hint="Create one with `kankuro init <dir>` or pass --project <dir>")
    with open(p) as f:
        try:
            spec = json.load(f)
        except json.JSONDecodeError as e:
            raise CliError("bad_spec", f"{p} is not valid JSON: {e}")
    validate(spec, project)
    return spec


def save(project, spec):
    validate(spec, project)
    tmp = project_path(project) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(spec, f, indent=2)
    os.replace(tmp, project_path(project))


def color(value, field, palette=None):
    """#RRGGBB or a colour name (`kankuro catalog colors`) -> '#rrggbb'."""
    if value is None:
        return None
    named = appearance.named_color(value, palette)
    if named:
        return named
    if not isinstance(value, str) or not HEX.match(value):
        names = ", ".join(appearance.PALETTES[palette]) if palette else "see `kankuro catalog colors`"
        raise CliError("bad_color", f"{field}: '{value}' is not a hex colour or a known colour name",
                       hint=f"Use #RRGGBB (e.g. #a0522d) or a name: {names}")
    return "#" + value.lstrip("#").lower()


def _palette(path):
    return {"skin.color": "skin", "eyes.iris_color": "eyes", "skin.brow_color": "hair"}.get(path)


def validate(spec, project):
    if spec.get("version") != VERSION:
        raise CliError("bad_spec", f"Unsupported spec version {spec.get('version')}")
    morph.resolve_macros(spec["body"].get("macros"))
    morph.target_weights(spec["body"].get("macros"), spec["body"].get("morphs"))
    h = spec["body"].get("height_cm")
    if h is not None and not (50 <= float(h) <= 250):
        raise CliError("bad_value", "body.height_cm must be between 50 and 250")
    color(spec["skin"].get("color"), "skin.color")
    color(spec["skin"].get("brow_color"), "skin.brow_color")
    color(spec["eyes"].get("iris_color"), "eyes.iris_color")
    if spec["skin"].get("texture"):
        _check_file(project, spec["skin"]["texture"], "skin.texture")
    for key in appearance.BROW_KEYS:
        if spec["skin"].get(key) is not None:
            appearance.check_brow(key, spec["skin"][key])
    appearance.validate_shape(spec.get("face", {}).get("shape") or {})
    shapes = spec.get("face", {}).get("blendshapes", "arkit52")
    if shapes not in ("arkit52", "none"):
        raise CliError("bad_value", f"Unknown face.blendshapes '{shapes}'", hint="Valid: arkit52, none")
    hair = spec.get("hair")
    if hair:
        if hair.get("source"):
            _check_file(project, hair["source"], "hair.source")
        elif hair["style"] not in catalog.HAIR_STYLES:
            raise CliError("unknown_hair", f"Unknown hair style '{hair['style']}'",
                           hint=f"Valid: {', '.join(catalog.HAIR_STYLES)}")
        color(hair.get("color"), "hair.color")
        if hair.get("texture"):
            _check_file(project, hair["texture"], "hair.texture")
    ids = set()
    for g in spec["garments"]:
        if g["id"] in ids:
            raise CliError("duplicate_garment", f"Duplicate garment id '{g['id']}'")
        ids.add(g["id"])
        if g.get("source"):
            _check_file(project, g["source"], f"garments[{g['id']}].source")
        elif g["type"] not in catalog.GARMENTS:
            raise CliError("unknown_garment", f"Unknown garment type '{g['type']}'",
                           hint=f"Valid: {', '.join(catalog.GARMENTS)}")
        color(g.get("color"), f"garments[{g['id']}].color")
        for key in ("texture", "normal", "height"):
            if g.get(key):
                _check_file(project, g[key], f"garments[{g['id']}].{key}")
        _check_material(project, g.get("material"), f"garments[{g['id']}].material")
        for name, ref in (g.get("material_regions") or {}).items():
            field = f"garments[{g['id']}].material_regions.{name}"
            ref = _check_material(project, ref, field)
            if name not in matlib.REGIONS and not ref.get("mask"):
                raise CliError("bad_value", f"{field}: region '{name}' needs a mask",
                               hint="Built-in regions: " + ", ".join(matlib.REGIONS) + "; others need \"mask\": <png>")
    _validate_attachments(spec, project)


def check_bone(name, field="bone", extra=()):
    """A Mesh2Motion bone name (or one of `extra`, e.g. another chain's bones)."""
    names = catalog.m2m_bones()
    if name not in names and name not in extra:
        raise CliError("unknown_bone", f"{field}: unknown bone '{name}'",
                       hint="Valid Mesh2Motion bones: " + ", ".join(names))
    return name


ID = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


def check_id(i, field):
    if not isinstance(i, str) or not ID.match(i):
        raise CliError("bad_value", f"{field}: id '{i}' must start with a letter and use letters, digits, _ or -")


def _vec(v, field, n=3):
    if not (isinstance(v, (list, tuple)) and len(v) == n and all(isinstance(x, (int, float)) for x in v)):
        raise CliError("bad_value", f"{field}: expected {n} numbers", hint="e.g. 0,0,0.02")


def _validate_attachments(spec, project):
    """accessories[], extra_bones[] and props[]: ids unique across them and the garments."""
    seen = {g["id"] for g in spec.get("garments", [])}
    chain_bones = []
    for c in spec.get("extra_bones") or []:
        f = f"extra_bones[{c.get('id')}]"
        check_id(c.get("id"), f)
        if c["id"] in seen:
            raise CliError("duplicate_id", f"{f}: id '{c['id']}' is already used")
        seen.add(c["id"])
        check_bone(c.get("parent"), f + ".parent", chain_bones)
        n = c.get("count", 6)
        if not isinstance(n, int) or not 1 <= n <= 32:
            raise CliError("bad_value", f"{f}.count must be 1..32")
        if c.get("follow") not in (None, "hair"):
            raise CliError("bad_value", f"{f}.follow must be 'hair'")
        if c.get("material"):
            _check_material(project, c["material"], f + ".material")
        color(c.get("color"), f + ".color")
        chain_bones += [f"{c['id']}_{k + 1:02d}" for k in range(n)]
    for a in spec.get("accessories") or []:
        f = f"accessories[{a.get('id')}]"
        check_id(a.get("id"), f)
        if a["id"] in seen:
            raise CliError("duplicate_id", f"{f}: id '{a['id']}' is already used")
        seen.add(a["id"])
        if a.get("file"):
            _check_file(project, a["file"], f + ".file")
        elif a.get("builtin") not in catalog.ACCESSORIES:
            raise CliError("unknown_accessory", f"{f}: needs a file or a built-in",
                           hint="Built-ins: " + ", ".join(catalog.ACCESSORIES))
        check_bone(a.get("bone"), f + ".bone", chain_bones)
        if a.get("fit", "none") not in catalog.ACCESSORY_FITS:
            raise CliError("bad_value", f"{f}.fit must be one of " + ", ".join(catalog.ACCESSORY_FITS))
        for k in ("offset", "rotate"):
            if a.get(k) is not None:
                _vec(a[k], f"{f}.{k}")
        if a.get("material"):
            _check_material(project, a["material"], f + ".material")
        color(a.get("color"), f + ".color")
    for pr in spec.get("props") or []:
        f = f"props[{pr.get('id')}]"
        check_id(pr.get("id"), f)
        if pr["id"] in seen:
            raise CliError("duplicate_id", f"{f}: id '{pr['id']}' is already used")
        seen.add(pr["id"])
        if pr.get("file"):
            _check_file(project, pr["file"], f + ".file")
        elif pr.get("builtin") not in catalog.PROPS:
            raise CliError("unknown_prop", f"{f}: needs a file or a built-in", hint="Built-ins: " + ", ".join(catalog.PROPS))
        if pr.get("hand") not in ("l", "r", "both"):
            raise CliError("bad_value", f"{f}.hand must be l, r or both")
        if pr.get("grip") and pr["grip"] not in catalog.GRIPS:
            raise CliError("unknown_grip", f"{f}: unknown grip '{pr['grip']}'", hint="Valid: " + ", ".join(catalog.GRIPS))
        for k in ("offset", "rotate"):
            if pr.get(k) is not None:
                _vec(pr[k], f"{f}.{k}")
        if pr.get("material"):
            _check_material(project, pr["material"], f + ".material")
        color(pr.get("color"), f + ".color")


def _check_material(project, ref, field):
    if ref is None:
        return None
    ref = matlib.normalize(ref)
    if "preset" not in ref:
        raise CliError("bad_value", f"{field}: needs a preset name", hint='e.g. "gold" or {"preset": "gem", "color": "#1f5fbf"}')
    matlib.check(ref["preset"], field)
    color(ref.get("color"), field + ".color")
    if ref.get("mask"):
        _check_file(project, ref["mask"], field + ".mask")
    return ref


def _check_file(project, rel, field):
    if not os.path.exists(os.path.join(project, rel)):
        raise CliError("missing_file", f"{field}: file '{rel}' not found in project",
                       hint="Files are copied into <project>/assets when you add them; re-add it")


def import_file(project, src, kind):
    """Copy an external file into <project>/assets/<kind>/ and return its project-relative path."""
    if not os.path.isfile(src):
        raise CliError("missing_file", f"File not found: {src}")
    d = os.path.join(project, "assets", kind)
    os.makedirs(d, exist_ok=True)
    base = os.path.basename(src)
    dst = os.path.join(d, base)
    stem, ext = os.path.splitext(base)
    i = 1
    while os.path.exists(dst) and not os.path.samefile(src, dst):
        if _same_content(src, dst):
            break
        dst = os.path.join(d, f"{stem}_{i}{ext}")
        i += 1
    if not os.path.exists(dst):
        shutil.copyfile(src, dst)
    return os.path.relpath(dst, project)


def _same_content(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def parse_value(raw):
    """Parse a CLI value: JSON when possible (numbers, null, true, lists), else a plain string."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


SETTABLE = {
    "name": str,
    "body.preset": str,
    "body.height_cm": (int, float, type(None)),
    "skin.color": str,
    "skin.roughness": (int, float),
    "skin.lips": bool,
    "skin.brows": bool,
    "skin.detail": bool,
    "skin.brow_color": (str, type(None)),
    "eyes.iris_color": (str, type(None)),
    "face.blendshapes": str,
    **{f"skin.{k}": (int, float) for k in appearance.BROW_KEYS},
    "export.hide_body_under_clothes": bool,
    "export.texture_size": int,
}


def set_path(spec, path, value):
    """Set a dotted path. body.macros.<slider>, body.morphs.<modifier> and the SETTABLE keys are allowed."""
    spec = copy.deepcopy(spec)
    parts = path.split(".")
    if path.startswith("body.macros.") and len(parts) == 3:
        if value is None:
            spec["body"]["macros"].pop(parts[2], None)
        else:
            if not isinstance(value, (int, float)):
                raise CliError("bad_value", f"{path} must be a number 0..1")
            if parts[2] not in morph.MACROS:
                raise CliError("unknown_macro", f"Unknown body slider '{parts[2]}'",
                               hint=f"Valid: {', '.join(morph.MACROS)}")
            spec["body"]["macros"][parts[2]] = float(value)
        return spec
    if path.startswith("body.morphs."):
        name = path[len("body.morphs."):]
        if value is None or value == 0:
            spec["body"]["morphs"].pop(name, None)
        else:
            if not isinstance(value, (int, float)):
                raise CliError("bad_value", f"{path} must be a number")
            if name not in morph.modifier_catalog():
                raise CliError("unknown_modifier", f"Unknown morph modifier '{name}'",
                               hint="Run `kankuro morphs list` (optionally --search <text>)")
            spec["body"]["morphs"][name] = float(value)
        return spec
    if path.startswith("face.shape.") and len(parts) == 4:
        name = path[len("face.shape."):]
        shape = spec.setdefault("face", {}).setdefault("shape", {})
        if value is None or value == 0:
            appearance.clamp(name, 0)
            shape.pop(name, None)
        else:
            shape[name] = appearance.clamp(name, value)
        return spec
    if path not in SETTABLE:
        raise CliError("bad_path", f"Cannot set '{path}'",
                       hint="Settable: body.macros.<slider>, body.morphs.<modifier>, face.shape.<slider>, "
                       + ", ".join(SETTABLE)
                       + ". Use the hair/garment commands for hair and clothes.")
    if not isinstance(value, SETTABLE[path]) or (SETTABLE[path] is not bool and isinstance(value, bool)):
        raise CliError("bad_value", f"Wrong type for {path}: {value!r}")
    if path == "body.preset":
        if value not in PRESETS:
            raise CliError("unknown_preset", f"Unknown preset '{value}'", hint=f"Valid: {', '.join(PRESETS)}")
        spec["body"]["preset"] = value
        spec["body"]["macros"] = dict(PRESETS[value])
        return spec
    node = spec
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    if path.endswith("color") and value is not None:
        value = color(value, path, _palette(path))
    if path[len("skin."):] in appearance.BROW_KEYS:
        value = appearance.check_brow(path[len("skin."):], value)
    node[parts[-1]] = value
    return spec


def effective_morphs(spec):
    """body.morphs with the face.shape sliders merged in: what `build` actually applies."""
    return appearance.effective_morphs(spec)
