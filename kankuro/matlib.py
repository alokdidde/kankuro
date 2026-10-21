"""Material presets: metals, gems, pearl, lacquer and zari thread (no Blender).

Each preset is a set of Principled BSDF values that export as glTF PBR metallic-roughness (plus
KHR_materials_transmission/ior for gems, clearcoat for lacquer and pearl, anisotropy for brushed steel).
Metal colours are the measured reflectance (F0) of the metal, written as sRGB: a metal's base colour is
the colour of its reflection, so they look pale here and rich once rendered.

Garments use them through `material` (the whole garment) or `material_regions` (a masked area of the UV
template such as the border); accessories and props take `material` too."""
from .errors import CliError

# kind: metal | thread (metallic yarn woven into cloth: keeps the fabric relief) | dielectric | gem
# color: default base colour (sRGB hex); --color overrides it
# metallic / roughness / specular: Principled values (specular = Specular IOR Level, 0.5 = F0 of 4%)
# anisotropy: stretched highlight (brushed metal); coat / coat_roughness: clear lacquer layer
# transmission / ior: light passing through (gems); subsurface: soft inner glow (pearl)
# thin_film: thin-film interference thickness in nm (pearl's nacre shimmer; KHR_materials_iridescence)
MATERIALS = {
    "gold": {"desc": "Polished yellow gold (jewellery, crowns, armour trim)", "kind": "metal",
             "color": "#fcd88a", "metallic": 1.0, "roughness": 0.2},
    "rose_gold": {"desc": "Rose gold (gold-copper alloy)", "kind": "metal",
                  "color": "#f7c9ae", "metallic": 1.0, "roughness": 0.22},
    "brass": {"desc": "Brass (lamps, vessels, buttons, temple bells)", "kind": "metal",
              "color": "#f2d892", "metallic": 1.0, "roughness": 0.3},
    "bronze": {"desc": "Bronze (armour, statues, old weapons)", "kind": "metal",
               "color": "#d9a878", "metallic": 1.0, "roughness": 0.38},
    "silver": {"desc": "Polished silver (anklets, jewellery)", "kind": "metal",
               "color": "#fbf8f2", "metallic": 1.0, "roughness": 0.16},
    "steel": {"desc": "Brushed steel (blades, armour)", "kind": "metal",
              "color": "#c8c9cb", "metallic": 1.0, "roughness": 0.28, "anisotropy": 0.5},
    "iron_dark": {"desc": "Dark forged iron (old weapons, chains)", "kind": "metal",
                  "color": "#6e6b67", "metallic": 1.0, "roughness": 0.55},
    "gem": {"desc": "Cut gemstone; colour with --color (default ruby red)", "kind": "gem",
            "color": "#c2102e", "metallic": 0.0, "roughness": 0.02, "specular": 0.5, "transmission": 1.0,
            "ior": 1.76},
    "pearl": {"desc": "Pearl (soft lustre with a faint rainbow shimmer)", "kind": "dielectric",
              "color": "#f1ebdf", "metallic": 0.0, "roughness": 0.32, "specular": 0.5, "coat": 0.8,
              "coat_roughness": 0.18, "subsurface": 0.15, "thin_film": 380},
    "gold_zari": {"desc": "Gold zari: metallic thread woven into the cloth (saree/dhoti borders); keeps the "
                          "fabric's weave relief", "kind": "thread",
                  "color": "#e6c27a", "metallic": 0.85, "roughness": 0.38},
    "lacquer": {"desc": "Glossy lacquer over a coloured base (bangles, wood, leather); colour with --color",
                "kind": "dielectric", "color": "#8a1a17", "metallic": 0.0, "roughness": 0.4, "specular": 0.5,
                "coat": 1.0, "coat_roughness": 0.04},
}

# region masks drawn from a garment's UV template: "border" = a band along every open edge (hems,
# neckline, cuffs, the saree's long edges and pallu end; not the sewn seams), "hem" = the band along the
# lowest open edges only. The width comes from the garment (catalog `border`) or the region's own `width`.
REGIONS = ("border", "hem")


def check(name, field="material"):
    if name not in MATERIALS:
        raise CliError("unknown_material", f"{field}: unknown material '{name}'",
                       hint="Valid: " + ", ".join(MATERIALS) + " (see `kankuro catalog materials`)")
    return MATERIALS[name]


def normalize(m):
    """A material reference is a preset name or {"preset": name, "color": hex, "roughness": f}."""
    if m is None:
        return None
    return {"preset": m} if isinstance(m, str) else dict(m)


def resolve(m, color=None, roughness=None):
    """Full parameter set for a material reference, with overrides applied (the reference's own colour
    and roughness first, then the explicit arguments)."""
    m = normalize(m)
    out = dict(check(m["preset"]))
    out["preset"] = m["preset"]
    for k in ("color", "roughness"):
        if m.get(k) is not None:
            out[k] = m[k]
    if color:
        out["color"] = color
    if roughness is not None:
        out["roughness"] = roughness
    return out


def summary():
    """`catalog materials`: every preset with its parameter values."""
    return {k: {kk: vv for kk, vv in v.items()} for k, v in MATERIALS.items()}
