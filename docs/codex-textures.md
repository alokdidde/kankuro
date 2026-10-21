# Garment textures from Codex (or any image model)

The CLI never calls an image model. You generate the images outside it and pass them in as files.
Each garment can take up to three images. All three are painted on the **same UV template**.

| file | required | what it is | flag |
|---|---|---|---|
| `<name>_albedo.png` | yes | the colour/print of the fabric, flat lit | `--texture` |
| `<name>_height.png` | recommended | greyscale relief: white = raised, black = sunk, mid grey = flat | `--height` |
| `<name>_normal.png` | optional | tangent-space normal map, OpenGL convention (green = up) | `--normal` |

Prefer a **height map over a normal map**. Image models paint height maps reliably because they are
just greyscale. Normal maps they often get wrong: the colour channels end up mixed up, or lighting
gets baked in. The CLI turns the height map into a correct normal map itself. Even with no height
map, the CLI adds its own fabric relief (weave, stitching, folds) from the garment's `--fabric`
preset, so a plain albedo still looks 3D.

## 1. Get the template

```bash
ccreator template tshirt            # -> templates/tshirt_template.png and templates/tshirt_mask.png
ccreator template all               # every garment type in the catalog
```

The template is 2048×2048. The **left half is the front** of the garment and the **right half is
the back, seen from behind** (so its left side is the wearer's left). The grey shape is the
garment's flat sketch, and the labels and seam lines are only guides. The mask is pure white where
the garment is.

Send Codex the template PNG as the input image along with the prompt.

## 2. File specs (all three images)

- PNG, 2048×2048 (1024 or 4096 also work: the CLI resizes), sRGB for the albedo.
- **Exactly the template layout.** Don't move, rotate, mirror, crop or rescale the shape.
- Fill the whole grey shape and bleed the colour ~20 px past its outline. Outside the shape doesn't
  matter.
- No guide labels, grid lines, outlines, shadows, lighting, highlights, folds-as-shading, mannequin
  or background objects. It must be a flat fabric swatch cut to the shape.
- The front and back halves must meet at the seams: the same colour and pattern scale on both sides
  of the shoulders, side seams and sleeves.
- Pattern scale: the template is about 1 m of fabric across its width, so a 2 cm stripe is about
  40 px.

## 3. Prompts

Replace the bracketed parts. Send each prompt with the template image.

### Albedo (colour)

```
Using the attached UV template, paint a flat texture map for a [dark indigo denim jacket with
light topstitching, two chest pockets with buttoned flaps and a small leather brand patch on the
back]. Keep the exact layout: the left half is the front of the garment, the right half is the
back seen from behind. Fill the entire grey shape edge to edge and bleed 20 px past its outline.
Remove all labels, guide lines and the grey. Flat, evenly lit, albedo only: no shadows, no
highlights, no ambient occlusion, no folds or wrinkles drawn as shading, no perspective, no
model or mannequin. Pockets, seams, trims and prints must sit in the right places on front and
back and line up across the shoulder and side seams. Output a 2048x2048 PNG.
```

### Height (relief), generated after the albedo

Send the **albedo you just got** as the input image (not the template), so the details line up:

```
Convert the attached garment texture into a matching greyscale height map at the same
2048x2048 size and exact same layout. Mid grey (128) is the base fabric surface. Raised details
are lighter: seams and topstitching thread, pocket and flap edges, buttons, rivets, embroidery,
appliques, ribbing, cable knit, quilting puffs. Recessed details are darker: seam grooves,
pleats, quilting stitch lines, gaps between panels. Add a faint fabric weave at the right scale
[fine diagonal twill]. Keep it subtle and smooth with no hard noise. Do not include shading,
lighting, colours or print artwork: a printed logo is flat, so it stays mid grey unless it is
embroidered or rubber. Pure greyscale PNG.
```

### Normal map (optional; use only if the height map isn't enough)

```
Convert the attached greyscale height map into a tangent-space normal map at the same size and
layout, OpenGL convention: red = +X (right), green = +Y (up), blue = +Z out of the surface.
Flat areas are exactly RGB (128,128,255). Raised edges facing up are greener and edges facing
right are redder. No lighting or colour, PNG.
```

Check it: a flat area must be the light-blue (128,128,255). If bumps look inverted in the render,
the green channel is flipped (DirectX convention). Drop the normal map and use the height map.

### More albedo subjects

Use these in the `[...]` slot of the albedo prompt:

- tshirt: `heather grey cotton T-shirt with a large faded retro sunset print on the chest and a
  small print between the shoulder blades on the back, ribbed collar`
- longsleeve: `cream cable-knit wool sweater, ribbed cuffs and hem` (use `--fabric knit`)
- jacket: `olive canvas field jacket with four patch pockets, brass snaps and a corduroy collar`
- pants: `black cargo trousers with side thigh pockets and knee panels`
- skirt: `red and navy tartan pleated skirt`
- boots: `worn brown leather work boots with stitched toe cap and dark welt` (use `--fabric leather`)

## 4. Bring them into the CLI

```bash
ccreator garment set jacket --texture ./jacket_albedo.png --height ./jacket_height.png --fabric canvas
ccreator garment set jacket --normal ./jacket_normal.png        # optional, blended on top
ccreator garment set jacket --normal-strength 1.5               # more/less relief (default 1)
ccreator render --focus upper --views front,three_quarter,back
ccreator build
```

`--fabric` chooses the built-in micro-relief that goes under your maps: `cotton`, `denim`, `knit`,
`canvas`, `leather`, `silk`, `spandex`, or `none` to use only your maps. When the Codex height map
already has the weave in it, `--fabric silk` (smooth, keeps stitching and folds) or `none` avoids
doubling it.

The files are copied into `<project>/assets/` and baked into `build/work/garment_<id>_albedo.jpg` and
`garment_<id>_normal.jpg`, which go into the GLB as `baseColorTexture` and `normalTexture`.
