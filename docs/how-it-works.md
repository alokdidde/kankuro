# How it works

The details behind each feature: what kankuro does under the hood, and the options that tune it.
For every command and flag, see [cli-reference.md](cli-reference.md).

## Body and skeleton

The body is the MakeHuman base mesh driven by Character-Creator-style sliders (gender, age, muscle,
weight, height, proportions, ethnicity mix, breast size) plus 238 detailed morphs. The skeleton is the
exact **Mesh2Motion human rig**: 65 bones plus `root`, Unreal-style names, T-pose rest and identical
bone orientations, so every Mesh2Motion animation plays unchanged. Bone positions are fitted to each
body from MakeHuman's joint helpers, the mesh is posed into the Mesh2Motion T-pose, and skin weights
(at most 4 influences, normalised) come from MakeHuman's CC0 weights mapped onto the Mesh2Motion bones.
`kankuro validate` checks names, hierarchy, rest orientations and weights.

## Hair

11 procedural styles (including Indian and French braids and Indian loose hair) grown from the current scalp, or your own mesh. Procedural hair is built
  from **hair cards**: hundreds of narrow ribbons with an alpha strand texture, combed along each style's
  flow and layered over a darker base, so it reads as locks of hair rather than a solid helmet.
  **Eyebrows** are individual strand cards too, and follow the ARKit brow blendshapes.
  See [examples/hair_styles.png](../examples/hair_styles.png) and [examples/hair_before_after.png](../examples/hair_before_after.png).

## Clothes and textures

```bash
kankuro template tshirt          # templates/tshirt_template.png + tshirt_mask.png (2048 px)
#   -> give the template to the image model: "paint a denim shirt design on this flat sketch,
#      left = front, right = back seen from behind, keep inside the grey shape"
kankuro garment set tshirt --texture ./denim_shirt.png
kankuro garment set tshirt --height ./denim_shirt_height.png   # optional: greyscale relief, white = raised
kankuro render --views front,back
```

The **saree** has its own layout: the pleated skirt's front and back flat sketches at the bottom and
the **pallu** unrolled as one long strip across the top (left = the end tucked at the right hip, then
across the chest and over the left shoulder, right = the hanging end at the back). Paint the zari border
along the strip's long edges and the skirt hem, and the decorated pallu end at the strip's right end.
Wear it over `blouse`. `tools/saree_texture.py MASK OUT` paints a simple silk saree on that layout
without an image model (`examples/saree_silk.png`).

Every garment also gets **fabric relief** baked into a normal map, so clothes don't look flat even
with a plain colour. Each garment type has a default fabric (`catalog fabrics`: cotton, jersey, denim, knit,
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
[docs/codex-textures.md](codex-textures.md) has the exact image-model prompts and file specs.

**Metal, gems and zari.** `--material PRESET` gives a whole garment a material preset (gold, bronze,
steel, gem, pearl, lacquer...; `catalog materials`), and `--material-region border=gold_zari` puts a
preset on part of the UV template: a band along the open edges (`border`, `hem`) measured on the
unfolded cloth, or your own `--mask`. A region takes the preset's colour, metallic and roughness through
a glTF metallic-roughness texture (`build/work/garment_<id>_mr.png`) and keeps the cloth's weave relief,
folds and occlusion, so a zari border still reads as woven thread. `render` shows metal against a
studio environment (bright ceiling, darker floor, two softbox strips) that only reflections see; the
backdrop stays plain grey. [Materials](cli-reference.md#materials) has an image of every preset.

The UV layout comes from a fixed reference body, so **one texture fits that garment on every body
shape**. `kankuro template body` gives the skin layout (MakeHuman UVs) for `kankuro skin --texture`.

### Custom garments and hair

```bash
kankuro reference-body --out ref.glb          # neutral T-pose body to model on
kankuro garment import --file hat.glb --id hat --color "#6b4f2a"
kankuro hair import --file braids.glb --color "#2a1a10"
```

Imported meshes are moved onto the current body shape (a smooth displacement field from reference
body to current body), skinned from nearby body weights, and pushed out of the skin.

## Auto-rigging other meshes

```bash
kankuro autorig model.glb --out model_rigged.glb --animations Idle_A --render ./check
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
kankuro face list [--group nose]                  # sliders with ranges and descriptions, presets, current values
kankuro face set nose.width=0.4 jaw.width=-0.3 chin.projection=0.5   # 0 removes a slider
kankuro face preset angular                       # angular soft round long heart square delicate rugged aquiline broad
kankuro face preset heart --amount 0.6 --add      # blend a preset on top of the current sliders
kankuro face randomize --seed 42 --strength 0.5   # a new, plausible face; same seed = same face
kankuro face randomize --groups nose,mouth --seed 3   # re-roll only some features
kankuro face reset [--groups eyes]
```

Slider groups: `head` (width, length, depth, fat, age, and 0..1 blends towards oval, round, square,
rectangular, triangular, heart, diamond), `forehead`, `brows` (brow ridge: height, tilt, ridge), `eyes`,
`nose`, `mouth`, `jaw`, `chin`, `cheeks`, `ears`, `neck`. Bipolar sliders run -1..1 with 0 = unchanged;
about ±0.3 is a subtle change, ±0.6 clear, ±1 extreme. `--strength` for `randomize`: 0.3 subtle, 0.5
natural (the default), 1 caricature. The seed is saved in `face.seed`.
The raw MakeHuman modifiers (`kankuro morphs`) still work and add to the sliders.

**Colours.** Every colour option takes `#RRGGBB` or a name from its palette (`kankuro catalog colors`):

```bash
kankuro skin --color tan              # whole body. porcelain fair light light_olive medium olive tan golden_brown
                                       #   brown dark_brown deep ebony (+ pale_grey orc_green blue)
kankuro hair set long --color auburn  # black soft_black dark_brown brown chestnut auburn copper ginger light_brown
                                       #   dark_blonde blonde platinum ash_blonde grey salt_pepper white + dyed colours
kankuro hair set --color platinum     # recolour the current hair, keep the style
```

**Eyes.** Iris colour plus the `eyes.*` sliders, without the prefix:

```bash
kankuro eyes --color hazel size=0.3 tilt=0.4 monolid=0.5
#   colours: dark_brown brown light_brown amber hazel green grey_green grey blue light_blue steel_blue violet red gold
#   shape:   size spacing height tilt (up = cat-eye) openness width lid_crease lid_fold monolid bags
```

**Eyebrows.** Hair shape and colour, plus the brow-ridge sliders (`brows.*`):

```bash
kankuro brows --preset arched --color dark_brown   # natural thin thick bushy straight arched sparse short
kankuro brows --thickness 1.3 --arch -0.5 --density 1.2 --length 0.9 height=0.2 ridge=0.3
kankuro brows --color hair                         # follow the hair colour (the default)
kankuro brows --off                                # no eyebrows
```

`--thickness` 0.3..2 (1 natural), `--arch` -1 flat .. 1 high, `--density` 0.2..2, `--length` 0.5..1.4. They
are stored as `skin.brow_thickness`, `brow_arch`, `brow_density`, `brow_length` and `skin.brow_color`.

[examples/face_variety.png](../examples/face_variety.png) shows eight characters made only with these commands
(`tools/face_variety.sh` rebuilds it).

## Facial rig: ARKit 52 blendshapes

`build` adds the 52 ARKit blendshapes with their standard names to `Body`, `Eyes`, `LowerTeeth` and
`Tongue`. Engines drive them by name, so face-capture data or a lip-sync tool plays on the character
directly. They don't touch the skeleton, so the Mesh2Motion rig and its clips are unchanged.

```bash
kankuro render --focus head --expression smile                  # presets: smile laugh surprise angry sad blink kiss
kankuro render --focus head --expression jawOpen=0.6,eyeBlinkLeft=1,smile
kankuro catalog expressions                                     # the 52 names and the presets
kankuro set face.blendshapes=none                               # leave them out (smaller GLB)
```

The shapes are generated for each character from MakeHuman's CC0 face data, so they fit any body and face
shape:

* 59 **face pose units** on MakeHuman's face skeleton drive the jaw, eye look, lips, cheeks and tongue.
* Hand-sculpted **expression targets** cover blink, squint, smile, frown, pucker, brows and nose. They are
  blended by the character's ethnicity sliders.

Left and right are the character's own, as in ARKit. They add about 5 s to a build and about 3 MB to the
GLB. `validate` checks that all 52 names are present. Teeth and tongue are MakeHuman's simple helper
shapes, so they look plain in close-ups.
