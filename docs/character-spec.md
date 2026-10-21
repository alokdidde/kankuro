# The character spec (`character.json`)

A project's whole character is one JSON file. The CLI commands edit it for you and validate every
change, but you can also write it by hand or generate it, then run `kankuro build`. Every command
that loads the project checks it, so a mistake shows up as a normal JSON error with a hint.

## Example

```json
{
  "version": 1,
  "name": "Mira",
  "body": {
    "preset": "athletic_female",
    "macros": {
      "gender": 0.0, "muscle": 0.6, "weight": 0.45, "proportions": 0.8, "age": 0.45,
      "asian": 0.7, "caucasian": 0.3, "african": 0.0
    },
    "morphs": {
      "nose/nose-scale-horiz-decr|incr": -0.3,
      "chin/chin-prominent-decr|incr": 0.2
    },
    "height_cm": 168
  },
  "skin": {
    "color": "#c68e6b", "texture": null, "roughness": 0.6,
    "lips": true, "brows": true, "brow_color": "#2a1a12",
    "brow_thickness": 0.85, "brow_arch": 0.8, "brow_density": 1.0, "brow_length": 1.0
  },
  "eyes": {"iris_color": "#4a3020"},
  "face": {"blendshapes": "arkit52",
           "shape": {"head.heart": 0.8, "chin.width": -0.6, "eyes.tilt": 0.3, "nose.tip_up": 0.2}},
  "hair": {"style": "ponytail", "color": "#1e1410"},
  "garments": [
    {"id": "tanktop", "type": "tanktop", "color": "#f2efe8"},
    {"id": "jacket", "type": "jacket", "color": "#3d5a40", "fabric": "denim",
     "texture": "assets/textures/bomber_olive.png"},
    {"id": "pants", "type": "pants", "color": "#2b2b33"},
    {"id": "boots", "type": "boots"}
  ],
  "export": {"animations": ["Idle_A", "Walk"], "hide_body_under_clothes": true, "texture_size": 2048}
}
```

## Fields

### Top level

| field | type | meaning |
|---|---|---|
| `version` | `1` | spec format version |
| `name` | string | character name; the default GLB is `build/<name>.glb` |
| `body` | object | shape |
| `skin` | object | skin material |
| `eyes` | object | eye colour |
| `face` | object | face shape sliders and facial blendshapes |
| `hair` | object or `null` | `null` is bald |
| `garments` | array | clothes, in any order (layers decide stacking) |
| `export` | object | build options |

### `body`

| field | type | meaning |
|---|---|---|
| `preset` | string | the preset the sliders started from (informational once sliders change) |
| `macros` | object | body sliders, each 0..1. Missing sliders use their defaults. See [cli-reference.md#set](cli-reference.md#set) for the list. |
| `morphs` | object | detailed morphs, `name: value`. Names come from `kankuro morphs`. Two-sided morphs (`a|b` in the name) take −1..1, one-sided ones 0..1. |
| `height_cm` | number or `null` | exact standing height, 50 to 250. `null` lets the `height` slider decide. |

### `skin`

| field | type | default | meaning |
|---|---|---|---|
| `color` | hex | `#d8a383` | whole-body skin tone (commands also accept names like `tan`, stored as hex) |
| `texture` | path or `null` | `null` | PNG on the body UV layout (`kankuro template body`); replaces the flat tone |
| `roughness` | number | 0.6 | material roughness |
| `lips` | bool | true | tint the lips |
| `brows` | bool | true | eyebrows on or off (individual strand cards, see [hair](cli-reference.md#hair)) |
| `brow_color` | hex or `null` | `null` | eyebrow colour; `null` follows the hair colour |
| `brow_thickness` | 0.3..2 | 1.0 | eyebrow band height (0.5 thin, 1.6 bushy) |
| `brow_arch` | -1..1 | 0.0 | -1 flat/straight, 1 high arch |
| `brow_density` | 0.2..2 | 1.0 | hair count (0.4 sparse, 1.6 dense) |
| `brow_length` | 0.5..1.4 | 1.0 | how far the tail reaches toward the temple |

`kankuro brows` sets the last five (with presets); see [cli-reference.md#brows](cli-reference.md#brows).

### `eyes`

| field | type | meaning |
|---|---|---|
| `iris_color` | hex or `null` | recolours the iris; `null` keeps the default brown eye texture |

### `face`

| field | type | default | meaning |
|---|---|---|---|
| `blendshapes` | `arkit52` or `none` | `arkit52` | export the 52 ARKit facial blendshapes as morph targets |
| `shape` | object | `{}` | face sliders, `"group.name": value` (e.g. `"nose.width": 0.4`); merged into `body.morphs` at build time. Names and ranges: `kankuro face list` or [cli-reference.md#face](cli-reference.md#face) |
| `seed` | int | absent | the seed of the last `face randomize` |

### `hair`

Either a procedural style:

```json
{"style": "bob", "color": "#3b2a1e", "texture": null}
```

or an imported mesh:

```json
{"style": "custom", "source": "assets/meshes/braids.glb", "color": "#2a1a10", "texture": null}
```

`style` is one of `buzz`, `short`, `bob`, `long`, `ponytail`, `bun`, `indian_braid`, `french_braid`, `indian_loose`, `afro`, `mohawk`, or `custom`
with a `source`.

### `garments[]`

| field | type | meaning |
|---|---|---|
| `id` | string | unique in the project; commands use it |
| `type` | string | a garment type from `kankuro catalog garments`, or `custom` for an imported mesh |
| `source` | path | imported mesh (only for `custom`) |
| `color` | hex | base colour (multiplies the texture) |
| `texture` | path | albedo on the garment's UV template |
| `fabric` | string | relief preset (`cotton` woven, `jersey`, `denim`, `knit`, `canvas`, `leather`, `silk`, `spandex`) or `none`; missing = the type's default |
| `height` | path | greyscale relief on the template, white = raised |
| `normal` | path | tangent-space normal map on the template (OpenGL, green up) |
| `normal_strength` | number | scales the final normal map |
| `roughness` | number | material roughness |
| `layer` | int | stacking order override; higher is further out |
| `hide_body` | bool | `false` keeps the skin under this garment |

### `export`

| field | type | default | meaning |
|---|---|---|---|
| `animations` | array of clip names | `[]` | clips `build` bakes in when `--animations` isn't given |
| `hide_body_under_clothes` | bool | true | delete body faces fully covered by clothing (prevents poke-through) |
| `texture_size` | int | 2048 | resolution of baked garment albedo and normal maps |

## Paths

Every path (`texture`, `source`, `height`, `normal`) is **relative to the project folder**. When you
use the CLI, files are copied into `assets/textures/` or `assets/meshes/` for you. When you write the
spec by hand, put the files inside the project yourself. A missing file fails with `missing_file`.

## Editing by hand

```bash
kankuro show > /dev/null          # check the current spec is valid
$EDITOR character.json
kankuro show                      # validates it again; errors explain what's wrong
kankuro build
```

`kankuro set` can't reach garments or hair (use `garment set` and `hair set`), but editing those
entries in the JSON directly is fine.
