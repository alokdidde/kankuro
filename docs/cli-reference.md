# CLI reference

Every command and option, with what it prints. For a guided walk-through, start with
[getting-started.md](getting-started.md).

The command is `kankuro`. `ccreator` is the same program under its original name (the Python
package is `ccreator`, so `python -m ccreator` works too). Examples here use `kankuro`.

```
kankuro [-p PROJECT] [--version] <command> [options]
```

## Contents

* [How the CLI behaves](#how-the-cli-behaves): output, exit codes, projects, files
* Project and spec: [init](#init) · [show](#show) · [set](#set) · [catalog](#catalog) · [morphs](#morphs) · [skin](#skin)
* Hair and clothes: [hair](#hair) · [garment](#garment) · [template](#template)
* Output: [render](#render) · [build](#build) · [animations](#animations)
* Assets and rigging: [reference-body](#reference-body) · [autorig](#autorig) · [validate](#validate)
* [schema](#schema)
* [Error codes](#error-codes)

---

## How the CLI behaves

### One JSON object per command

Every command prints **exactly one JSON object** on stdout, and nothing else. Blender's own
log never reaches stdout.

```json
{"ok": true, "command": "set", "changed": {"body.height_cm": 183}, "spec": {"...": "..."}}
```

```json
{"ok": false, "command": "set", "error": {
  "code": "unknown_macro",
  "message": "Unknown body slider 'nope'",
  "hint": "Valid: gender, age, muscle, weight, height, proportions, african, asian, caucasian, breast_size, breast_firmness"}}
```

* `ok` tells you whether it worked. On failure, `error.code` is a stable identifier you can branch
  on, `error.message` says what went wrong and `error.hint` usually says how to fix it.
* Output is pretty-printed. Set `CCREATOR_COMPACT=1` to get one line per command, which is easier
  to parse from scripts.

### Exit codes

| code | meaning |
|---|---|
| `0` | success |
| `2` | bad input: wrong argument, unknown name, missing file. Read `error.hint`. |
| `1` | internal error. `error.traceback` holds the last lines of the Python traceback, and Blender's own output is in `<project>/build/blender.log`. |

### Projects

A **project** is a folder with a `character.json` in it (the spec, see
[character-spec.md](character-spec.md)). Commands that work on a character find the project in this
order:

1. `-p DIR` / `--project DIR` (goes **before** the command: `kankuro -p ./hero build`)
2. the `CCREATOR_PROJECT` environment variable
3. the current directory

`init`, `catalog`, `morphs`, `animations`, `reference-body`, `autorig`, `validate` and `schema` don't
need a project.

### Files you pass in are copied

Textures and meshes given to `skin`, `hair` and `garment` are copied into
`<project>/assets/textures/` or `<project>/assets/meshes/`, and the spec stores the
project-relative path. A project folder is therefore self-contained: zip it and it builds anywhere.

### Project layout

```
hero/
  character.json          the spec (edit with commands, or by hand)
  assets/textures/        copied textures
  assets/meshes/          copied custom meshes
  templates/              UV templates written by `template`
  renders/                PNGs written by `render`
  build/<name>.glb        the exported character
  build/manifest.json     what the last build produced
  build/blender.log       Blender's own log
  build/work/             intermediate textures (baked albedo/normal maps)
```

### Units and conventions

Metres, feet on the ground at z = 0. The character faces −Y in Blender (+Z in glTF) and rests in a
T-pose. The skeleton is the Mesh2Motion human rig: 65 bones plus `root`, with Unreal-style names
(`pelvis`, `spine_01..03`, `neck_01`, `head`, `clavicle_l`, `upperarm_l`, `lowerarm_l`, `hand_l`,
fingers `*_01..03`, `thigh_l`, `calf_l`, `foot_l`, `ball_l`, ...). Skin weights use at most 4
influences per vertex, normalised.

Colours are always hex: `#RRGGBB` (the `#` is optional). Quote them in shells where `#` starts a
comment: `--color "#3d5a40"`.

---

## Project and spec commands

These only edit `character.json`. They are instant and don't start Blender.

### init

Create a project.

```
kankuro init <dir> [--preset PRESET] [--name NAME] [--force]
```

| option | default | meaning |
|---|---|---|
| `<dir>` | | folder to create (it may already exist) |
| `--preset` | `neutral` | starting body: `neutral`, `female`, `male`, `athletic_female`, `athletic_male`, `heavy_male`, `child`, `elder_female`, `elder_male` |
| `--name` | folder name | character name; also the GLB file name |
| `--force` | | overwrite an existing `character.json` |

Prints `{"project": "<abs dir>", "spec": {...}}`. Fails with `exists` if the folder already has a
spec and `--force` wasn't given.

```bash
kankuro init ./ava --preset athletic_female --name Ava
```

### show

Print the spec, plus the last build's manifest if there is one.

```
kankuro show
```

Prints `{"project", "spec", "last_build"?}`.

### set

Change one or more values in the spec.

```
kankuro set PATH=VALUE [PATH=VALUE ...]
```

Values are parsed as JSON when they can be (`0.6`, `183`, `true`, `null`), otherwise as a string.
`null` resets a value.

| path | type | meaning |
|---|---|---|
| `body.macros.<slider>` | 0..1 | a body slider (see the table below); `null` returns it to the preset |
| `body.morphs.<modifier>` | number | a detailed morph (see [morphs](#morphs)); `0` or `null` removes it |
| `body.preset` | string | switch preset; **resets all sliders** to that preset |
| `body.height_cm` | 50..250 or `null` | exact standing height; the body is scaled to it after the sliders |
| `skin.color` | hex | skin tone |
| `skin.roughness` | number | skin roughness (default 0.6) |
| `skin.lips` / `skin.brows` | bool | tinted lips / painted eyebrows on or off |
| `skin.brow_color` | hex or `null` | eyebrow colour (`null` = a darker shade of the skin tone) |
| `eyes.iris_color` | hex or `null` | iris colour (`null` = the default brown eye texture) |
| `face.blendshapes` | `arkit52` or `none` | facial blendshapes in the GLB (default `arkit52`, see [Facial expressions](#facial-expressions)) |
| `export.hide_body_under_clothes` | bool | delete body faces fully covered by clothes (default `true`, avoids poke-through) |
| `export.texture_size` | int | resolution of baked garment maps (default 2048) |
| `name` | string | character name |

**Body sliders** (`body.macros.*`, all 0..1):

| slider | default | meaning |
|---|---|---|
| `gender` | 0.5 | 0 = female, 1 = male |
| `age` | 0.5 | 0 = 1 year, 0.1875 = 10 y, 0.5 = 25 y, 1 = 90 y |
| `muscle` | 0.5 | 0 = minimal tone, 1 = very muscular |
| `weight` | 0.5 | 0 = thin, 1 = heavy |
| `height` | 0.5 | 0 = short, 1 = tall, relative to gender and age (use `body.height_cm` for an exact height) |
| `proportions` | 0.5 | 0 = uncommon, 0.5 = regular, 1 = idealised |
| `african`, `asian`, `caucasian` | 0.333 | ethnic blend; the three are normalised to sum to 1 |
| `breast_size` | 0.5 | 0 = small, 1 = large (female shapes) |
| `breast_firmness` | 0.5 | 0 = soft, 1 = firm |

```bash
kankuro set body.macros.gender=0.9 body.macros.muscle=0.7 body.height_cm=183 \
            skin.color=#8d5524 eyes.iris_color=#3a6ea5
kankuro set "body.morphs.nose/nose-scale-horiz-decr|incr=0.4"   # quote: the name has a |
kankuro set body.height_cm=null                                   # back to slider height
```

Prints `{"changed": {...}, "spec": {...}}`. Errors: `bad_assignment`, `bad_path`, `bad_value`,
`unknown_macro`, `unknown_modifier`, `unknown_preset`, `bad_color`.

### catalog

List what's available.

```
kankuro catalog [presets|body_sliders|hair_styles|garments|fabrics|expressions]
```

With no section it prints everything. Garment entries include `slot`, `layer` and default
`fabric`. `expressions` lists the 52 ARKit blendshape names and the expression presets. See [Garment types](#garment-types) for the current list.

### morphs

List the 238 detailed MakeHuman morphs (face, torso, limbs, ...).

```
kankuro morphs [--group GROUP] [--search TEXT]
```

Groups: `armslegs`, `breast`, `buttocks`, `cheek`, `chin`, `ears`, `eyebrows`, `eyes`, `forehead`,
`genitals`, `head`, `hip`, `mouth`, `neck`, `nose`, `pelvis`, `stomach`, `torso`.

Each entry has a `name` and a `range`. Names with a `decr|incr` (or `in|out`, `up|down`, ...) pair
take −1..1: negative moves towards the first word, positive towards the second. Single-sided ones
take 0..1.

```bash
kankuro morphs --group nose
kankuro morphs --search jaw
kankuro set "body.morphs.chin/chin-prognathism-decr|incr=0.3"
```

### skin

Skin tone, a painted skin texture, and eyebrow colour.

```
kankuro skin [--color HEX] [--texture PNG | --texture ""] [--brow-color HEX]
```

* `--texture` takes a PNG painted on the body UV layout (`kankuro template body` gives the layout).
  Pass an empty string to remove it.

Prints `{"skin": {...}}`.

---

## Hair and clothes

### hair

```
kankuro hair set <style> [--color HEX] [--texture PNG]
kankuro hair import --file MESH [--color HEX] [--texture PNG]
kankuro hair remove
```

**Styles** (procedural, grown from the current scalp so they fit any head):

| style | look |
|---|---|
| `buzz` | very short, follows the scalp (use under a `turban`) |
| `short` | short layered cut with some volume |
| `bob` | chin-length bob |
| `long` | straight, past the shoulders |
| `ponytail` | pulled back into a ponytail |
| `bun` | pulled back into a bun |
| `afro` | big rounded afro |
| `mohawk` | shaved sides, tall centre crest |

`hair set` keeps the current colour if you don't pass `--color` (default `#3b2a1e`).

`hair import` takes your own hair mesh (`.glb`, `.gltf`, `.obj`, `.fbx`) modelled on the reference
body (see [reference-body](#reference-body)). It's moved onto the current head shape and skinned
automatically.

Prints `{"hair": {...}}` (`null` after `remove`).

### garment

```
kankuro garment add <type> [--id ID] [--color HEX] [--texture PNG] [--fabric NAME] [--keep-slot] [surface options]
kankuro garment import --file MESH --id ID [--color HEX] [--texture PNG] [surface options]
kankuro garment set <id> [--color HEX] [--texture PNG|""] [--layer N] [--hide-body true|false] [surface options]
kankuro garment remove <id>
```

**Slots.** Each garment type has a slot (`top`, `bottom`, `outer`, `feet`, `hands`, `head`, `shawl`).
`garment add` **replaces** any garment already in that slot and lists what it removed in
`replaced`. Pass `--keep-slot` to wear two things in one slot (a tank top under a shirt, say).

**Layers.** Inner layers have lower numbers. Outer garments are fitted over the ones beneath them,
and body skin under clothing is hidden so it can't poke through. `--layer N` overrides the order.

| option | used with | meaning |
|---|---|---|
| `<type>` | add | a garment type from the table below |
| `<id>` | set, remove | the garment's id (defaults to its type) |
| `--id` | add, import | id to give it; needed to add two of the same type |
| `--file` | import | your mesh, modelled on the reference body |
| `--color` | all | base colour (multiplies the texture if there is one) |
| `--texture` | all | albedo PNG painted on the garment's UV template; `""` removes it |
| `--fabric` | all | surface relief preset (`cotton`, `denim`, `knit`, `canvas`, `leather`, `silk`, `spandex`) or `none` |
| `--height` | all | greyscale relief PNG on the UV template; white = raised. Added on top of the fabric. `""` removes it |
| `--normal` | all | tangent-space normal map PNG (OpenGL, green = up) on the template; blended in. `""` removes it |
| `--normal-strength` | all | scale for the final normal map (default 1.0) |
| `--roughness` | all | material roughness |
| `--layer` | all | stacking order override |
| `--hide-body` | all | `false` keeps the body skin under this garment |
| `--keep-slot` | add, import | don't replace the garment already in this slot |

Prints `{"garment": {...}, "garments": [...], "replaced"?: [...]}`.

#### Garment types

| type | slot | layer | default fabric | description |
|---|---|---|---|---|
| `tshirt` | top | 1 | cotton | short-sleeve crew-neck T-shirt |
| `longsleeve` | top | 1 | cotton | long-sleeve crew-neck top |
| `tanktop` | top | 1 | cotton | sleeveless tank top |
| `blouse` | top | 1 | silk | cropped sari blouse (choli): short sleeves, scoop neck |
| `kurta` | top | 2 | cotton | knee-length tunic, 3/4 sleeves, flared, side slits |
| `jacket` | outer | 3 | canvas | loose long-sleeve outer layer covering the hips |
| `pants` | bottom | 2 | denim | full-length trousers |
| `shorts` | bottom | 2 | denim | mid-thigh shorts |
| `leggings` | bottom | 0 | spandex | skin-tight, ankle length |
| `skirt` | bottom | 2 | cotton | knee-length skirt |
| `long_skirt` | bottom | 2 | silk | ankle-length skirt |
| `churidar` | bottom | 0 | cotton | fitted ankle-length trousers gathered over the lower leg |
| `dhoti` | bottom | 2 | canvas | draped, loose legs from waist to mid-calf |
| `saree` | bottom | 3 | silk | Nivi drape: pleated skirt plus pallu over the left shoulder; wear over `blouse` |
| `dupatta` | shawl | 4 | silk | long scarf across the chest and over both shoulders |
| `shoes` | feet | 2 | leather | closed shoes with a sole |
| `boots` | feet | 3 | leather | mid-calf boots |
| `gloves` | hands | 2 | leather | full-finger gloves |
| `turban` | head | 4 | canvas | wrapped turban (pagdi); pair with `buzz` hair |

`kankuro catalog garments` always has the current list.

```bash
kankuro garment add tshirt --color "#eeeeee"
kankuro garment add tanktop --keep-slot               # under the T-shirt
kankuro garment add jacket --color "#3d5a40" --fabric denim
kankuro garment set jacket --texture ./camo.png --height ./camo_height.png
kankuro garment remove jacket
```

### template

Write UV templates so an image model (or a person) can paint new garment textures.

```
kankuro template [TARGET ...] [--out DIR] [--size PX]
```

| option | default | meaning |
|---|---|---|
| `TARGET` | `all` | garment ids in the project, garment types, `body`, or `all` (the project's garments plus `body`; every type if the project has no garments) |
| `--out` | `<project>/templates` | output folder |
| `--size` | 2048 | image size in pixels (square) |

For each target it writes `<id>_template.png` (the garment's flat sketch, seam lines and labels on a
white background) and `<id>_mask.png` (white where the texture is used). For most garments the
**left half is the front** and the **right half is the back, seen from behind**. The `saree` has its
own layout, described in its template's labels.

The UV layout is computed on a fixed reference body, so **one texture fits a garment type on every
body shape**.

```bash
kankuro template tshirt            # templates/tshirt_template.png + tshirt_mask.png
kankuro template body --size 4096  # skin layout for `kankuro skin --texture`
```

Prints `{"templates": {"<id>": {"template", "mask", "layout", "size"}}, "how_to_retexture": "..."}`.
Imported (custom) garments keep their own UVs and fail with `custom_garment`.

The full retexturing workflow, with ready-made image-model prompts, is in
[codex-textures.md](codex-textures.md).

---

## Output

`render`, `build`, `template` and `animations` start Blender (headless, inside the Python process).
Building a character takes roughly 5 to 20 seconds on a laptop CPU.

### render

Preview PNGs, rendered with Cycles on the CPU. Use them to check the result visually.

```
kankuro render [--views V1,V2,...] [--focus full|upper|head]
               [--animation CLIP --frame F] [--expression EXPR]
               [--size PX] [--samples N] [--out DIR] [--prefix NAME]
```

| option | default | meaning |
|---|---|---|
| `--views` | `front,three_quarter,side,back` | any of those four, comma-separated |
| `--focus` | `full` | `upper` frames the top half; `head` is a face and hair close-up |
| `--animation` | | pose the character from a Mesh2Motion clip (see [animations](#animations)) |
| `--frame` | 0.25 | with `--animation`: 0..1 is a fraction of the clip, above 1 is a frame number |
| `--expression` | | a facial expression: a preset (`smile`, `laugh`, `surprise`, `angry`, `sad`, `blink`, `kiss`), ARKit weights (`jawOpen=0.6,eyeBlinkLeft=1`), or both (`smile,jawOpen=0.2`) |
| `--size` | 512 | image height in pixels |
| `--samples` | 12 | Cycles samples; raise for cleaner images, lower for speed |
| `--out` | `<project>/renders` | output folder |
| `--prefix` | `render` (or `pose_<clip>`) | file name prefix |

Writes one PNG per view plus a combined `<prefix>_sheet.png`.

```bash
kankuro render                                  # all four views
kankuro render --focus head --views front,three_quarter
kankuro render --animation Jog --frame 0.3      # check how clothes deform mid-stride
kankuro render --focus head --expression surprise
```

Prints `{"views": {"front": "<png>", ...}, "sheet": "<png>", "animation", "frame", "focus", "expression"?}`.

### build

Build the character and export a rigged GLB.

```
kankuro build [--out GLB] [--animations A,B,...|all] [--render] [--size PX] [--samples N]
```

| option | default | meaning |
|---|---|---|
| `--out` | `<project>/build/<name>.glb` | output path |
| `--animations` | the spec's `export.animations` | Mesh2Motion clips to bake in, comma-separated, or `all` (87 clips, a much bigger file) |
| `--render` | | also render preview views (`renders/build_*.png`) |
| `--size`, `--samples` | 512, 12 | for `--render` |

The GLB has the body, eyes, hair and each garment as separate skinned meshes, one armature, PBR
materials (garments get baked `baseColorTexture` and `normalTexture`), the requested clips, and
the 52 ARKit facial blendshapes as morph targets on the body.

#### Facial expressions

Every character is built with the 52 **ARKit blendshapes** (`jawOpen`, `eyeBlinkLeft`,
`mouthSmileRight`, `browInnerUp`, ...) as named glTF morph targets, so face-tracking apps, Unity,
Unreal Live Link and three.js can drive the face directly. `kankuro catalog expressions` lists the
names. Preview them with `render --expression`. To leave them out (a smaller file), run
`kankuro set face.blendshapes=none`.

Prints a manifest, also saved as `build/manifest.json`:

```json
{
  "ok": true, "command": "build",
  "glb": "/work/hero/build/hero.glb", "bytes": 5364852,
  "animations": ["Idle_A", "Jog"],
  "seconds": 12.43,
  "timings": {"body": 0.41, "body_meshes": 3.55, "garments": 3.67, "hide_body": 0.16, "export": 4.64},
  "meshes": [
    {"name": "Body", "vertices": 12250, "triangles": 24346, "materials": ["Skin"]},
    {"name": "Eyes", "vertices": 552, "triangles": 1060, "materials": ["Eyes"]},
    {"name": "tshirt", "vertices": 7352, "triangles": 14712, "materials": ["Garment_tshirt"]}
  ],
  "height_m": 1.735,
  "skeleton": {"standard": "mesh2motion-human", "bones": 66, "pose": "T"},
  "hidden_body_faces": 1205,
  "warnings": []
}
```

Read `warnings`: they flag things that built but may look wrong.

### animations

List the Mesh2Motion clips that `build --animations` and `render --animation` accept.

```
kankuro animations
```

Prints `{"count": 87, "clips": [{"name": "Idle_A", "frames": [0, 75], "seconds": 2.5}, ...]}`.
Clips include idles (`Idle_A`, `Idle_Talking`, ...), locomotion (`Walk`, `Jog`, `Sprint`,
`Crouch_Walk`, `Swim_Fwd`, ...), combat (`Punch_Jab`, `Sword_Attack`, `Pistol_Shoot`, ...), and
actions (`Sitting_Idle`, `PickUp_Table`, `Farm_Watering`, ...). Names ending in `_RM` have root
motion.

---

## Assets and rigging

### reference-body

Export the neutral T-pose body to model custom hair or garments on.

```
kankuro reference-body --out GLB [--with-rig]
```

Model on top of it in any 3D tool, export GLB/OBJ/FBX, then use `hair import` or `garment import`.
Imported meshes are moved onto each character's body shape with a smooth displacement field,
skinned from nearby body weights, and pushed out of the skin. `--with-rig` includes the skeleton
and skin weights.

### autorig

Rig any humanoid mesh to the Mesh2Motion skeleton. It doesn't need a project.

```
kankuro autorig <mesh> --out GLB [--facing auto|-y|+y|-x|+x] [--animations A,B] [--render DIR]
                [--method auto|heat|proximity]
```

| option | default | meaning |
|---|---|---|
| `<mesh>` | | `.glb`, `.gltf`, `.obj` or `.fbx` |
| `--out` | | output GLB |
| `--facing` | `auto` | which way the model faces (`-y`, `+y`, `-x`, `+x`); `auto` detects it from the feet |
| `--animations` | | clips to bake in |
| `--render` | | folder for check renders (front and side, at rest and posed) |
| `--method` | `auto` | skinning: `heat` (bone heat), `proximity` (distance), `auto` tries heat first and falls back |

What works: upright humanoids in T- or A-pose, dressed or not, realistic or cartoon proportions.
Legs must be separate below the knees. A long robe that hides the crotch fails with
`autorig_failed`. Models taller than 20 units are taken as centimetres and scaled to metres.

The output reports the detected `facing`, the skinning method used (`skinning.method`), and every
joint position, so you can check it. A log is written next to the output as `autorig.log`.

```bash
kankuro autorig robot.glb --out robot_rigged.glb --animations Idle_A,Walk --render ./check
```

### validate

Check a GLB against the Mesh2Motion human standard: bone names and hierarchy, rest orientations,
T-pose, skin weights.

```
kankuro validate <glb>
```

Prints `{"valid": true|false, "checks": [{"check": "bone_names", "pass": true, "detail": ...}, ...]}`. Use it after `build` or `autorig`; any check with `"pass": false` says what is off.

---

## schema

```
kankuro schema
```

A machine-readable summary of every command, the spec file name and the conventions. It's the
quickest thing for an agent to read first.

---

## Error codes

| code | when | what to do |
|---|---|---|
| `bad_arguments` | the command line didn't parse | `kankuro schema` or `kankuro <command> --help` |
| `missing_arg` | a required argument is missing | read `hint` |
| `no_project` | no `character.json` where it looked | `kankuro init <dir>`, or pass `-p` |
| `exists` | `init` on a folder that has a spec | add `--force` |
| `bad_spec` | `character.json` is not valid JSON or has the wrong version | fix or recreate it |
| `bad_assignment` | `set` argument without `=` | `path=value` |
| `bad_path` | `set` on a path that can't be set | see the table under [set](#set) |
| `bad_value` | wrong type or out of range | read `message` |
| `bad_color` | not a hex colour | `#RRGGBB` |
| `unknown_preset`, `unknown_macro`, `unknown_modifier`, `unknown_hair`, `unknown_garment`, `unknown_fabric`, `unknown_animation` | a name not in the catalog | `hint` lists valid names |
| `duplicate_garment` | a garment with that id exists | `--id <other>` or `garment set` |
| `no_garment` | no garment with that id | `hint` lists current ids |
| `custom_garment` | `template` on an imported garment | it keeps its own UVs |
| `missing_file` | a file you passed, or one the spec refers to, doesn't exist | check the path |
| `bad_format`, `no_mesh` | an imported mesh can't be read | use `.glb`, `.gltf`, `.obj` or `.fbx` with a mesh in it |
| `bad_view`, `bad_focus`, `bad_section`, `bad_expression` | an option value isn't recognised | `hint` lists valid values |
| `no_blendshapes` | `render --expression` on a character built with `face.blendshapes=none` | `kankuro set face.blendshapes=arkit52` |
| `autorig_failed` | the mesh isn't an upright humanoid with separate legs | read `message` |
| `no_blender` | `bpy` can't be imported | install `bpy==5.2.*` on Python 3.13 (see [installation.md](installation.md)) |
| `internal` | a bug | `error.traceback` and `build/blender.log`; please open an issue |
