<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.png">
    <img src="docs/images/logo.png" alt="kankuro logo: a marionette control bar holding a rigged mannequin" width="160">
  </picture>
</p>

<h1 align="center">kankuro</h1>

**A character creator CLI for AI agents.** Rigged, game-ready 3D humans from a small JSON spec,
in the spirit of Reallusion Character Creator, built on Blender and the Mesh2Motion skeleton.

[![CI](https://github.com/alokdidde/kankuro/actions/workflows/ci.yml/badge.svg)](https://github.com/alokdidde/kankuro/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/alokdidde/kankuro?include_prereleases)](https://github.com/alokdidde/kankuro/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20arm64%20%7C%20Windows-informational)

<p align="center">
  <img src="examples/saree_woman.png" alt="A character in a saree, front, side and back views" width="100%">
</p>

**[Install](docs/installation.md)** · **[Getting started](docs/getting-started.md)** ·
**[CLI reference](docs/cli-reference.md)** · **[For AI agents](docs/agents.md)** ·
**[Docs](docs/README.md)**

The command is `kankuro`; `ccreator` is the same command under its original name, and the examples
below use it.

It's meant to be driven by AI agents: every command prints one JSON object, errors
carry a `code` and a `hint`, the whole character lives in one inspectable `character.json`, and
`render` produces PNGs the agent can look at.

* **Body:** a MakeHuman base mesh with Character-Creator-style sliders (gender, age, muscle, weight,
  height, proportions, ethnicity mix, breast size) plus 238 detailed face and body morphs.
* **Skeleton:** the exact **Mesh2Motion human rig** (65 bones plus root, Unreal-style names, T-pose rest,
  identical bone orientations), so Mesh2Motion animations play unchanged. `validate` checks this.
* **Hair:** 11 procedural styles (including Indian and French braids and Indian loose hair) grown from the current scalp, or your own mesh. Procedural hair is built
  from **hair cards**: hundreds of narrow ribbons with an alpha strand texture, combed along each style's
  flow and layered over a darker base, so it reads as locks of hair rather than a solid helmet.
  **Eyebrows** are individual strand cards too, and follow the ARKit brow blendshapes.
  See [examples/hair_styles.png](examples/hair_styles.png) and [examples/hair_before_after.png](examples/hair_before_after.png).
* **Clothes:** 12 standard garments cut from the body and conformed to it, auto-skinned and layered,
  with skin hidden underneath. Each one has a **front/back UV template** that an image model can repaint.
  The repainted PNG is passed back in with `--texture`.
* **Facial expressions:** every build carries the **52 ARKit blendshapes** (`jawOpen`, `eyeBlinkLeft`,
  `mouthSmileRight`, ...) as glTF morph targets, ready for face capture (Live Link Face, ARKit, MediaPipe)
  or lip-sync tools.
* **Auto-rig:** rigs any humanoid mesh (T- or A-pose, dressed or not) to the Mesh2Motion skeleton.
* **Export:** GLB, optionally with Mesh2Motion animation clips baked in.

The CLI never calls an image model. New textures always come in as files.

## Install

Download the bundle for your platform from the
[latest release](https://github.com/alokdidde/kankuro/releases/latest), unpack it, and run
`./kankuro schema` (`kankuro.cmd schema` on Windows). Bundles include Python 3.13 and Blender's
`bpy`, so nothing else is needed. Linux x64, macOS Apple Silicon, Windows x64 and Windows ARM64
are supported.

Or with [uv](https://docs.astral.sh/uv/) / pip on Python 3.13:

```bash
uv tool install --python 3.13 git+https://github.com/alokdidde/kankuro
# or: pip install git+https://github.com/alokdidde/kankuro      (Python 3.13 only; bpy 5.2 needs it)
```

Everything runs headless on CPU. Previews use Cycles on CPU, so no GPU is needed. Details and
troubleshooting: [docs/installation.md](docs/installation.md).

## Quick start

```bash
ccreator init ./hero --preset athletic_male
cd hero                                   # or pass -p ./hero, or set CCREATOR_PROJECT
ccreator set body.height_cm=183 body.macros.weight=0.6
ccreator face preset angular && ccreator face randomize --seed 7 --strength 0.3 --add   # give it its own face
ccreator skin --color brown && ccreator eyes --color hazel && ccreator brows --preset thick
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

The **saree** has its own layout: the pleated skirt's front and back flat sketches at the bottom and
the **pallu** unrolled as one long strip across the top (left = the end tucked at the right hip, then
across the chest and over the left shoulder, right = the hanging end at the back). Paint the zari border
along the strip's long edges and the skirt hem, and the decorated pallu end at the strip's right end.
Wear it over `blouse`. `tools/saree_texture.py MASK OUT` paints a simple silk saree on that layout
without an image model (`examples/saree_silk.png`).

Every garment also gets **fabric relief** baked into a normal map, so clothes don't look flat even
with a plain colour. Each garment type has a default fabric (`catalog fabrics`: cotton, denim, knit,
canvas, leather, silk, spandex), and `--fabric NAME|none` overrides it. The relief combines the weave,
hem and seam stitching along the outline, soft folds, and compression creases at the elbows, wrists,
knees, ankles and waist (only where the cloth sits close to the body, so skirts and drapes stay smooth).
The albedo gets the look of real cloth rather than plastic: dye mottling, fibre heathering (white weft
on denim) and ambient occlusion baked from the dressed character (collars, armpits, layer overlaps).
Materials use cloth **sheen** with a low specular level (exported as `KHR_materials_sheen` /
`KHR_materials_specular`), which gives the soft, quasi-realistic look of game characters. A supplied `--height` map is added on top,
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

Any upright humanoid works: GLB/glTF/OBJ/FBX, T-pose or A-pose (arms down to ~70 degrees), with
clothes, hair and accessories, realistic or cartoon proportions (big heads, short legs). Legs must be
separate below the knees; a long skirt or robe that hides the crotch fails with `autorig_failed`.

- **Input clean-up.** Meshes are joined, any rig and clips in the file are dropped, and shape keys
  (blendshapes) are kept. If a rigged file's rest pose is broken (lying down, or parts scattered
  because only the skin assembles them), the pose the file shows is used instead.
- **Orientation and units.** Facing is detected from the feet (which way the toes point) and turned
  to face -Y; models facing sideways are handled too (`--facing -y|+y|-x|+x` overrides). A model
  taller than 20 units is taken as centimetres and scaled to metres (`scaled_by`).
- **Joints.** Landmarks are measured on the mesh: crotch (where the centre line between the legs
  becomes torso depth, so touching thighs or knees are fine), neck (narrowest point under the head),
  torso width, hand tips (furthest surface points from the chest, below the neck) and leg centre
  lines. The Mesh2Motion joints of the template body are mapped onto them. `joints` in the output
  gives every bone head in the input file's own coordinates, for checking.
- **Skinning.** Blender bone-heat on the mesh. Where heat can't solve it (glTF seams, open shells,
  many parts), heat runs on a welded copy, then on voxel remeshes from fine to coarse, and the
  weights are copied back by nearest surface point. Distance weights are the last resort. `skinning`
  reports what was tried and used.
- **Output.** Mesh2Motion T-pose rest with exact bone orientations, so every Mesh2Motion clip plays
  unchanged; `validate` checks it.

Check the renders: limbs should bend at the joints and the walk should look like the reference
body's. Tested on 33 Mesh2Motion sample characters (joint error against their hand-placed skeletons
is about 3% of height on average) plus Mixamo, VRM and glTF sample models.

## Face shape, skin, eyes, eyebrows and hair colour

Every face starts as the body sliders' average face (gender, age, ethnicity mix), so characters look alike
unless the face is shaped. The `face` command gives **68 named, symmetric sliders** over MakeHuman's face
targets, **10 archetype presets** and **seeded randomisation**. Values are stored in `face.shape` in
`character.json` and merged into the body morphs at build time.

```bash
ccreator face list [--group nose]                  # sliders with ranges and descriptions, presets, current values
ccreator face set nose.width=0.4 jaw.width=-0.3 chin.projection=0.5   # 0 removes a slider
ccreator face preset angular                       # angular soft round long heart square delicate rugged aquiline broad
ccreator face preset heart --amount 0.6 --add      # blend a preset on top of the current sliders
ccreator face randomize --seed 42 --strength 0.5   # a new, plausible face; same seed = same face
ccreator face randomize --groups nose,mouth --seed 3   # re-roll only some features
ccreator face reset [--groups eyes]
```

Slider groups: `head` (width, length, depth, fat, age, and 0..1 blends towards oval, round, square,
rectangular, triangular, heart, diamond), `forehead`, `brows` (brow ridge: height, tilt, ridge), `eyes`,
`nose`, `mouth`, `jaw`, `chin`, `cheeks`, `ears`, `neck`. Bipolar sliders run -1..1 with 0 = unchanged;
about ±0.3 is a subtle change, ±0.6 clear, ±1 extreme. `--strength` for `randomize`: 0.3 subtle, 0.5
natural (the default), 1 caricature. The seed is saved in `face.seed`.
The raw MakeHuman modifiers (`ccreator morphs`) still work and add to the sliders.

**Colours.** Every colour option takes `#RRGGBB` or a name from its palette (`ccreator catalog colors`):

```bash
ccreator skin --color tan              # whole body. porcelain fair light light_olive medium olive tan golden_brown
                                       #   brown dark_brown deep ebony (+ pale_grey orc_green blue)
ccreator hair set long --color auburn  # black soft_black dark_brown brown chestnut auburn copper ginger light_brown
                                       #   dark_blonde blonde platinum ash_blonde grey salt_pepper white + dyed colours
ccreator hair set --color platinum     # recolour the current hair, keep the style
```

**Eyes.** Iris colour plus the `eyes.*` sliders, without the prefix:

```bash
ccreator eyes --color hazel size=0.3 tilt=0.4 monolid=0.5
#   colours: dark_brown brown light_brown amber hazel green grey_green grey blue light_blue steel_blue violet red gold
#   shape:   size spacing height tilt (up = cat-eye) openness width lid_crease lid_fold monolid bags
```

**Eyebrows.** Hair shape and colour, plus the brow-ridge sliders (`brows.*`):

```bash
ccreator brows --preset arched --color dark_brown   # natural thin thick bushy straight arched sparse short
ccreator brows --thickness 1.3 --arch -0.5 --density 1.2 --length 0.9 height=0.2 ridge=0.3
ccreator brows --color hair                         # follow the hair colour (the default)
ccreator brows --off                                # no eyebrows
```

`--thickness` 0.3..2 (1 natural), `--arch` -1 flat .. 1 high, `--density` 0.2..2, `--length` 0.5..1.4. They
are stored as `skin.brow_thickness`, `brow_arch`, `brow_density`, `brow_length` and `skin.brow_color`.

[examples/face_variety.png](examples/face_variety.png) shows eight characters made only with these commands
(`tools/face_variety.sh` rebuilds it).

## Facial expressions (ARKit 52)

`build` adds the 52 ARKit blendshapes with their standard names to `Body`, `Eyes`, `LowerTeeth` and
`Tongue`. Engines drive them by name, so face-capture data or a lip-sync tool plays on the character
directly. They don't touch the skeleton, so the Mesh2Motion rig and its clips are unchanged.

```bash
ccreator render --focus head --expression smile                  # presets: smile laugh surprise angry sad blink kiss
ccreator render --focus head --expression jawOpen=0.6,eyeBlinkLeft=1,smile
ccreator catalog expressions                                     # the 52 names and the presets
ccreator set face.blendshapes=none                               # leave them out (smaller GLB)
```

The shapes are generated for each character from MakeHuman's CC0 face data, so they fit any body and face
shape:

* 59 **face pose units** on MakeHuman's face skeleton drive the jaw, eye look, lips, cheeks and tongue.
* Hand-sculpted **expression targets** cover blink, squint, smile, frown, pucker, brows and nose. They are
  blended by the character's ethnicity sliders.

Left and right are the character's own, as in ARKit. They add about 5 s to a build and about 3 MB to the
GLB. `validate` checks that all 52 names are present. Teeth and tongue are MakeHuman's simple helper
shapes, so they look plain in close-ups.

## Commands

Run `ccreator schema` for the machine-readable list. In brief:

| command | purpose |
|---|---|
| `init <dir> [--preset]` | new project (`catalog presets` lists presets) |
| `show` | spec + last build manifest |
| `set path=value ...` | `body.macros.<slider>`, `body.morphs.<modifier>`, `face.shape.<slider>`, `body.height_cm`, `skin.*`, `eyes.iris_color`, `face.blendshapes` (`arkit52`/`none`), `name` |
| `catalog [section]` | presets, body sliders, hair styles, garment types |
| `morphs [--group] [--search]` | detailed morph modifiers (nose, jaw, torso, limbs, ...) |
| `skin [--color] [--texture] [--brow-color]` | whole-body skin tone (hex or name) or painted skin texture |
| `face list/set/preset/randomize/reset` | face shape sliders, archetypes, seeded random faces |
| `eyes [--color] [slider=v ...]` | iris colour and eye shape |
| `brows [--preset] [--color] [--thickness --arch --density --length] [--on/--off]` | eyebrow shape and colour |
| `hair set/import/remove` | hair (`hair set --color X` recolours) |
| `garment add/import/set/remove` | clothes; `--texture`, `--fabric`, `--height`, `--normal` for surface; adding a garment replaces any other in the same slot unless `--keep-slot` |
| `template [ids|types|body|all]` | UV template + mask PNGs |
| `render [--views] [--focus] [--animation --frame] [--expression]` | preview PNGs + a combined sheet |
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
ccreator/face.py           ARKit 52 facial blendshapes from MakeHuman face units (numpy)
ccreator/appearance.py     face shape sliders, face presets, randomisation, named colours, eyebrow keys
ccreator/catalog.py        hair styles and garment definitions
ccreator/textures.py       skin map, UV templates
ccreator/fabric.py         fabric relief: weave/stitch/fold height -> normal map, albedo bake
ccreator/blender/*.py      body + skeleton fit, garments, hair, materials, render, anim, autorig, validate
ccreator/data/             compiled CC0 assets (tools/build_data.py regenerates them)
tests/test_cli.py          end-to-end tests (python -m unittest discover tests)
```

## Credits and licences

* MakeHuman base mesh, morph targets, skin weights, eyes, face pose units and expression targets: **CC0**
  (makehumancommunity/makehuman).
* Mesh2Motion human rig and animation clips: **CC0** (scottpetrovic/mesh2motion-app).
* `tools/build_data.py` recompiles `ccreator/data` from those repositories.

## Documentation

| | |
|---|---|
| [Installation](docs/installation.md) | bundles, pip/uv, platforms, troubleshooting |
| [Getting started](docs/getting-started.md) | a ten-minute walk-through |
| [CLI reference](docs/cli-reference.md) | every command, option, output and error code |
| [Character spec](docs/character-spec.md) | the `character.json` format |
| [For AI agents](docs/agents.md) | the JSON contract, a good loop, a system prompt snippet |
| [Garment textures](docs/codex-textures.md) | image-model prompts for retexturing clothes |
| [Development](docs/development.md) | tests, CI, multi-platform builds, releases |

## License

The code is [MIT](LICENSE). The bundled body, rig and animation data are CC0 (see above). Release
bundles also contain Python (PSF license) and Blender's `bpy` (GPL-3.0-or-later).
