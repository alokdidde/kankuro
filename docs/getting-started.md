# Getting started

This walks through making one character from scratch: body, face, hair, clothes, a custom
texture, previews, and a rigged GLB with animations. It takes about ten minutes. Install sasori
first ([installation.md](installation.md)).

Every command prints one JSON object. The snippets below show only the parts that matter.

## 1. Create a project

```bash
sasori init ./mira --preset athletic_female --name Mira
cd mira
```

The project is the folder. Everything about the character lives in `mira/character.json`, and every
file you add is copied into `mira/assets/`. Inside the folder you don't need `-p`; from elsewhere,
use `sasori -p ./mira <command>` or set `SASORI_PROJECT=./mira`.

Presets are just starting slider values: `neutral`, `female`, `male`, `athletic_female`,
`athletic_male`, `heavy_male`, `child`, `elder_female`, `elder_male`.

## 2. Shape the body

Body sliders run from 0 to 1:

```bash
sasori set body.macros.age=0.45 body.macros.weight=0.45 body.macros.muscle=0.6 \
            body.macros.asian=0.7 body.macros.caucasian=0.3 body.macros.african=0
sasori set body.height_cm=168
```

`body.height_cm` sets an exact height after the sliders. See all sliders with
`sasori catalog body_sliders`.

For finer control there are 238 detailed morphs:

```bash
sasori morphs --group nose                       # what's there
sasori set "body.morphs.nose/nose-scale-horiz-decr|incr=-0.3" \
            "body.morphs.chin/chin-prominent-decr|incr=0.2"
```

Quote morph names: they contain `|`, which shells treat as a pipe.

## 3. Skin and eyes

```bash
sasori skin --color "#c68e6b" --brow-color "#2a1a12"
sasori set eyes.iris_color=#4a3020
```

## 4. Hair

```bash
sasori catalog hair_styles
sasori hair set ponytail --color "#1e1410"
```

Hair is grown from the current scalp, so it fits whatever head shape you made.

## 5. Clothes

```bash
sasori garment add tanktop --color "#f2efe8"
sasori garment add jacket --color "#3d5a40"
sasori garment add pants --color "#2b2b33"
sasori garment add boots
```

Each garment has a slot (`top`, `bottom`, `outer`, `feet`, ...). Adding a second `bottom`
replaces the first, and the output tells you in `replaced`. Use `--keep-slot` to layer two things
in one slot. `sasori catalog garments` lists every type.

Each garment also gets a fabric preset (`denim` for pants, `canvas` for the jacket, ...) that bakes
weave, stitching and soft folds into a normal map, so even plain colours look like cloth:

```bash
sasori garment set jacket --fabric denim
```

## 6. Look at it

```bash
sasori render
```

```json
{"ok": true, "views": {"front": ".../renders/render_front.png", "...": "..."},
 "sheet": ".../renders/render_sheet.png"}
```

Open `renders/render_sheet.png`. It shows front, three-quarter, side and back. Closer looks:

```bash
sasori render --focus head --views front,three_quarter    # face and hair
sasori render --animation Jog --frame 0.3                 # clothes mid-stride
sasori render --focus head --expression smile             # ARKit facial blendshapes
```

Change things and render again until it looks right. Most iterations are a `set` or `garment set`
followed by a `render`.

## 7. Give the jacket a custom texture

sasori never generates images itself. It gives you a template, you (or an image model) paint on
it, and you pass the result back in.

```bash
sasori template jacket
# -> templates/jacket_template.png, templates/jacket_mask.png
```

The template is a flat sketch of the jacket: the left half is the front, the right half is the back
seen from behind. Paint the design over it at the same size, keeping it inside the grey shape. Then:

```bash
sasori garment set jacket --texture ./bomber_olive.png
sasori garment set jacket --height ./bomber_olive_height.png   # optional relief, white = raised
sasori render --views front,back
```

The texture fits the jacket on **any** body shape, because the UV layout comes from a fixed
reference body. [codex-textures.md](codex-textures.md) has copy-paste prompts for image models.

## 8. Build the GLB

```bash
sasori animations                          # 87 Mesh2Motion clips
sasori build --animations Idle_A,Walk,Jog
sasori validate build/Mira.glb
```

```json
{"ok": true, "glb": ".../build/Mira.glb", "animations": ["Idle_A", "Walk", "Jog"],
 "skeleton": {"standard": "mesh2motion-human", "bones": 66, "pose": "T"}, "warnings": []}
```

The GLB loads in Blender, Unity, Unreal, Godot, three.js and anything else that reads glTF. The
skeleton is the [Mesh2Motion](https://mesh2motion.org) human rig, so any Mesh2Motion animation
plays on it unchanged, and it retargets cleanly to Unreal-style humanoid rigs.

## 9. Rig a model you already have

`autorig` puts the same skeleton on any humanoid mesh, no project needed:

```bash
sasori autorig ~/models/knight.glb --out knight_rigged.glb --animations Idle_A,Walk --render ./knight_check
```

Look at `knight_check/` to see it posed. Limbs should bend at the joints.

## Where next

* [cli-reference.md](cli-reference.md): every command and option
* [character-spec.md](character-spec.md): editing `character.json` directly
* [agents.md](agents.md): driving sasori from an AI agent
* [codex-textures.md](codex-textures.md): image-model prompts for garment textures
