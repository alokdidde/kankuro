# Using sasori from an AI agent

sasori was built to be driven by agents (Claude Code, Codex, Cursor, your own tool-calling loop).
This page is what an agent needs to know. You can paste the [system prompt snippet](#system-prompt-snippet)
at the bottom straight into an agent's instructions.

## The contract

* **One JSON object on stdout per command.** Parse it. Never scrape logs. Set `SASORI_COMPACT=1`
  for single-line output.
* **`ok` first.** `true` means done. `false` means read `error.code` (stable, branch on it),
  `error.message` and `error.hint` (usually says exactly what to run instead).
* **Exit code 2** is your mistake (bad name, bad value, missing file). Fix the input and retry.
  **Exit code 1** is a sasori bug: `error.traceback` and `<project>/build/blender.log` explain it.
* **State lives in `character.json`.** Commands are idempotent edits of it. `sasori show` prints it.
  Nothing is hidden in a cache or a session.
* **Discover, don't guess.** `sasori --help` and `sasori <command> --help` (options plus worked
  examples), `sasori guide` (this guide; `sasori guide --list` for the CLI reference, spec format
  and texture guide), `sasori schema` (all commands as JSON), `sasori catalog` (presets, sliders,
  hair, garments, fabrics, colours), `sasori morphs --search <text>`, `sasori animations`.
* **Look at your work.** `sasori render` writes PNGs. An agent that can read images should open
  `renders/render_sheet.png` after visible changes.

## A good loop

```text
1. sasori guide; sasori catalog                  # learn the contract and what exists
2. sasori init <dir> --preset <closest preset>
3. sasori set ... / face ... / skin / eyes / brows / hair set ... / garment add ...  # rough pass from the brief
4. sasori render                                   # look at render_sheet.png
5. compare with the brief; adjust with set / garment set; render again
   (use --focus head for faces, --animation Jog --frame 0.3 for clothing in motion)
6. sasori build --animations <clips>; sasori validate <glb>
7. report the GLB path, the sheet PNG and the manifest's warnings
```

Keep renders cheap while iterating (`--size 384 --samples 8`) and raise them for the final look.

## Mapping a brief to settings

| brief says | do |
|---|---|
| "a tall, muscular man in his 40s" | `--preset athletic_male`, `set body.macros.age=0.65 body.height_cm=190` |
| "slim older woman" | `--preset elder_female`, `set body.macros.weight=0.3` |
| "East Asian features" | `set body.macros.asian=0.8 body.macros.caucasian=0.2 body.macros.african=0` |
| "a strong jaw, narrow nose" | `face set jaw.width=0.6 nose.width=-0.5` (`face list` shows every slider) |
| "a chiselled / round / heart-shaped face" | `face preset angular` (or `round`, `heart`, ...), then single `face set` tweaks |
| several characters that must not look alike | give each its own `face randomize --seed N` (alone, or `--add` on top of a preset) |
| "olive skin, hazel cat eyes" | `skin --color olive`, `eyes --color hazel tilt=0.5` |
| "thick dark eyebrows", "thin arched brows" | `brows --preset thick --color soft_black`, `brows --preset arched` |
| "auburn hair" | `hair set <style> --color auburn` (or `hair set --color auburn` to keep the style) |
| "a denim jacket" | `garment add jacket --fabric denim --color "#3b4f6b"` |
| "a printed T-shirt" | `template tshirt`, have an image model paint it (see [codex-textures.md](codex-textures.md)), `garment set tshirt --texture <png>` |
| "face tracking / lip sync / ARKit ready" | nothing to do: every build has the 52 ARKit blendshapes (`catalog expressions` lists them; `validate` checks them). `set face.blendshapes=none` leaves them out |
| "smiling" / "surprised" portrait | `render --focus head --expression smile` (presets or ARKit weights like `jawOpen=0.5`) |
| "wearing a turban" | `garment add turban`, `hair set buzz` (other styles poke through) |
| "traditional Indian dress" | `garment add blouse` + `garment add saree`, or `kurta` + `churidar` + `dupatta`, or `dhoti` + `turban` |
| "gold zari border", "gold armour" | `garment set saree --material-region border=gold_zari`, `garment set <id> --material bronze` (`catalog materials`) |
| "a gold crown and earrings", "bangles" | `accessory add circlet`, `accessory add ring_earring_l` / `_r`, `accessory add bangle_l`; your own mesh: `accessory add <id> --file <mesh> --bone head --material gold` |
| "holding a staff / sword / flute" | `prop add staff`, `prop add <id> --file <mesh> --hand r --grip power`, `prop add flute`; check `render --animation Walk` for `warnings` |
| "a monkey tail", "a long braid that swings" | `bones add tail --parent pelvis --count 8 --length 0.9 --radius 0.035`, `bones add braid --parent head --count 5 --follow hair` |

Age slider values: 0.1875 ≈ 10 years, 0.5 = 25, 0.75 ≈ 57, 1.0 = 90.

## Textures need an image model, outside sasori

sasori never calls an image model and needs no API key. When a texture is needed:

1. `sasori template <garment>` gives `<id>_template.png` and `<id>_mask.png`.
2. Hand the template to whatever image model you have, with a prompt from
   [codex-textures.md](codex-textures.md). Keep the output the same size and layout.
3. `sasori garment set <id> --texture <png>` (plus `--height <png>` for relief).
4. `sasori render --views front,back` and check it.

If no image model is available, a plain `--color` with a `--fabric` preset still looks like cloth.

## Common mistakes

| mistake | result | fix |
|---|---|---|
| `sasori build -p ./hero` | `bad_arguments` | `-p` goes before the command: `sasori -p ./hero build` |
| unquoted morph name | the shell treats `|` as a pipe | quote the whole assignment |
| `--color #ff0000` unquoted in some shells | `#` starts a comment, colour missing | `--color "#ff0000"` |
| two tops without `--keep-slot` | the first is replaced (see `replaced`) | add `--keep-slot` to layer them |
| `set hair.style=bob` | `bad_path` | `sasori hair set bob` |
| `--animations all` on every build | big, slow GLB | list the clips you need |

## Performance

Spec commands are instant. `render` and `build` start Blender inside the process and take roughly
5 to 20 seconds each on a laptop CPU; renders scale with `--size` and `--samples`. Commands are
independent processes, so separate projects can be built in parallel.

## System prompt snippet

```text
You can build rigged 3D characters with the `sasori` CLI.
- Every command prints one JSON object. Check "ok"; on failure read error.code and error.hint and fix the input.
- Start with `sasori guide` and `sasori catalog`; `sasori <command> --help` shows options and examples.
  Never guess names; use `catalog`, `morphs --search`, `face list`, `animations`.
- A project is a folder with character.json. Create it with `sasori init <dir> --preset <preset>`.
  Put -p <dir> BEFORE the command, or cd into the folder.
- Shape with `sasori set body.macros.<slider>=<0..1>` and `body.height_cm=<cm>`; quote morph names: "body.morphs.<name>=<v>".
- Face: every character needs its own face. Use `sasori face preset <archetype>`, `sasori face randomize --seed N`
  and `sasori face set <group.slider>=<-1..1>` (`sasori face list`). Eyes: `sasori eyes --color <name|#hex> tilt=..`.
  Eyebrows: `sasori brows --preset <name> --color <name|#hex>`. Skin: `sasori skin --color <name|#hex>`.
- Hair: `sasori hair set <style> --color "#hex"`. Clothes: `sasori garment add <type> --color "#hex" [--fabric name]`.
- Jewellery: `sasori accessory add <built-in|id --file mesh --bone B>`. Held objects: `sasori prop add <name>`.
  Tails and swinging braids: `sasori bones add <id> --parent <bone>`. The 65 standard bones never change.
- After visible changes run `sasori render` and look at renders/render_sheet.png. Use --focus head for faces.
- Custom fabric prints: `sasori template <id>`, get the image painted on that template outside sasori,
  then `sasori garment set <id> --texture <png>`.
- Finish with `sasori build --animations Idle_A,Walk` and `sasori validate <glb>`; report the GLB path and any warnings.
```
