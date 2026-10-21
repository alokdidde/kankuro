# ccreator: character creator CLI for AI agents

`ccreator` builds rigged, game-ready 3D humans from a small JSON spec, in the spirit of Reallusion
Character Creator. It's meant to be driven by AI agents: every command prints one JSON object, errors
carry a `code` and a `hint`, the whole character lives in one inspectable `character.json`, and
`render` produces PNGs the agent can look at.

* **Body:** a MakeHuman base mesh with Character-Creator-style sliders (gender, age, muscle, weight,
  height, proportions, ethnicity mix, breast size) plus 238 detailed face and body morphs.
* **Skeleton:** the exact **Mesh2Motion human rig** (65 bones plus root, Unreal-style names, T-pose rest,
  identical bone orientations), so Mesh2Motion animations play unchanged. `validate` checks this.
* **Hair:** 8 procedural styles grown from the current scalp, or your own mesh.
* **Clothes:** 12 standard garments cut from the body and conformed to it, auto-skinned and layered,
  with skin hidden underneath. Each one has a **front/back UV template** that an image model can repaint.
  The repainted PNG is passed back in with `--texture`.
* **Auto-rig:** rigs any humanoid mesh (T- or A-pose, dressed or not) to the Mesh2Motion skeleton.
* **Export:** GLB, optionally with Mesh2Motion animation clips baked in.

The CLI never calls an image model. New textures always come in as files.

## Install

```bash
pip install bpy==5.2.* numpy pillow     # bpy 5.2 needs Python 3.13
pip install -e .                         # provides the `ccreator` command (or use `python -m ccreator`)
```

Everything runs headless on CPU. Previews use Cycles on CPU, so no GPU is needed.

## Quick start

```bash
ccreator init ./hero --preset athletic_male
cd hero                                   # or pass -p ./hero, or set CCREATOR_PROJECT
ccreator set body.height_cm=183 body.macros.weight=0.6 skin.color=#8d5524 eyes.iris_color=#3a6ea5
ccreator hair set short --color "#1a1410"
ccreator garment add tshirt --color "#eeeeee"
ccreator garment add jacket --color "#3d5a40"
ccreator garment add pants --color "#2b2b33"
ccreator garment add boots
ccreator render --views front,side            # look at renders/render_sheet.png
ccreator render --focus head                  # face/hair close-up
ccreator render --animation Jog --frame 0.3   # check deformation in motion
ccreator build --animations Idle_A,Jog        # -> build/<name>.glb + build/manifest.json
ccreator validate build/hero.glb
```

## Retexturing clothes with an image model (outside the CLI)

```bash
ccreator template tshirt          # templates/tshirt_template.png + tshirt_mask.png (2048 px)
#   -> give the template to the image model: "paint a denim shirt design on this flat sketch,
#      left = front, right = back seen from behind, keep inside the grey shape"
ccreator garment set tshirt --texture ./denim_shirt.png
ccreator garment set tshirt --height ./denim_shirt_height.png   # optional: greyscale relief, white = raised
ccreator render --views front,back
```

Every garment also gets **fabric relief** baked into a normal map, so clothes don't look flat even
with a plain colour. Each garment type has a default fabric (`catalog fabrics`: cotton, denim, knit,
canvas, leather, silk, spandex), and `--fabric NAME|none` overrides it. The relief combines the weave,
hem and seam stitching along the outline, and soft folds. A supplied `--height` map is added on top,
and a supplied `--normal` map (OpenGL / +Y green) is blended in. `--normal-strength` scales the result.
The maps are written to `build/work/garment_<id>_albedo.jpg` and `_normal.jpg` and exported as glTF `baseColorTexture`
and `normalTexture`. `export.texture_size` (default 2048) sets their resolution.
[docs/codex-textures.md](docs/codex-textures.md) has the exact image-model prompts and file specs.

The UV layout comes from a fixed reference body, so **one texture fits that garment on every body
shape**. `ccreator template body` gives the skin layout (MakeHuman UVs) for `ccreator skin --texture`.

## Custom garments and hair

```bash
ccreator reference-body --out ref.glb          # neutral T-pose body to model on
ccreator garment import --file hat.glb --id hat --color "#6b4f2a"
ccreator hair import --file braids.glb --color "#2a1a10"
```

Imported meshes are moved onto the current body shape (a smooth displacement field from reference
body to current body), skinned from nearby body weights, and pushed out of the skin.

## Auto-rigging other meshes

```bash
ccreator autorig model.glb --out model_rigged.glb --animations Idle_A --render ./check
```

The model must be upright and humanoid, in T- or A-pose with legs apart. Facing is auto-detected from
the feet. Skinning uses Blender bone-heat. If heat can't solve the mesh, it tries a voxel-remeshed proxy,
then distance weights, and reports which method it used. The result is converted to the Mesh2Motion
T-pose rest.

## Commands

Run `ccreator schema` for the machine-readable list. In brief:

| command | purpose |
|---|---|
| `init <dir> [--preset]` | new project (`catalog presets` lists presets) |
| `show` | spec + last build manifest |
| `set path=value ...` | `body.macros.<slider>`, `body.morphs.<modifier>`, `body.height_cm`, `skin.*`, `eyes.iris_color`, `name` |
| `catalog [section]` | presets, body sliders, hair styles, garment types |
| `morphs [--group] [--search]` | detailed morph modifiers (nose, jaw, torso, limbs, ...) |
| `skin [--color] [--texture] [--brow-color]` | skin tone or painted skin texture |
| `hair set/import/remove` | hair |
| `garment add/import/set/remove` | clothes; `--texture`, `--fabric`, `--height`, `--normal` for surface; adding a garment replaces any other in the same slot unless `--keep-slot` |
| `template [ids|types|body|all]` | UV template + mask PNGs |
| `render [--views] [--focus] [--animation --frame]` | preview PNGs + a combined sheet |
| `build [--animations A,B|all] [--render]` | export the GLB |
| `animations` | Mesh2Motion clips available |
| `reference-body --out` | neutral body for authoring assets |
| `autorig <mesh> --out` | rig any humanoid |
| `validate <glb>` | check against the Mesh2Motion standard |

Exit codes: `0` ok, `2` bad input (`error.code` + `error.hint`), `1` internal error (with a traceback;
Blender's own log is in `build/blender.log`).

## Conventions

Units are metres, with the feet on z=0. The character faces −Y in Blender and +Z in glTF, with a T-pose
rest. Bones follow Mesh2Motion `rig-human` (`root`, `pelvis`, `spine_01..03`, `neck_01`, `head`,
`clavicle_l`, `upperarm_l`, `lowerarm_l`, `hand_l`, fingers `*_01..03` and leaves, `thigh_l`, `calf_l`,
`foot_l`, `ball_l`, ...). Skin weights use at most 4 influences, normalised.

## Layout

```
ccreator/cli.py            commands, JSON I/O
ccreator/spec.py           character.json schema, presets, validation
ccreator/morph.py          MakeHuman macro/detail morphs (numpy)
ccreator/catalog.py        hair styles and garment definitions
ccreator/textures.py       skin map, UV templates
ccreator/fabric.py         fabric relief: weave/stitch/fold height -> normal map, albedo bake
ccreator/blender/*.py      body + skeleton fit, garments, hair, materials, render, anim, autorig, validate
ccreator/data/             compiled CC0 assets (tools/build_data.py regenerates them)
tests/test_cli.py          end-to-end tests (python -m unittest discover tests)
```

## Credits and licences

* MakeHuman base mesh, morph targets, skin weights and eyes: **CC0** (makehumancommunity/makehuman).
* Mesh2Motion human rig and animation clips: **CC0** (scottpetrovic/mesh2motion-app).
* `tools/build_data.py` recompiles `ccreator/data` from those repositories.
