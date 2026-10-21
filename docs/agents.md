# Using kankuro from an AI agent

kankuro was built to be driven by agents (Claude Code, Codex, Cursor, your own tool-calling loop).
This page is what an agent needs to know. You can paste the [system prompt snippet](#system-prompt-snippet)
at the bottom straight into an agent's instructions.

## The contract

* **One JSON object on stdout per command.** Parse it. Never scrape logs. Set `KANKURO_COMPACT=1`
  for single-line output.
* **`ok` first.** `true` means done. `false` means read `error.code` (stable, branch on it),
  `error.message` and `error.hint` (usually says exactly what to run instead).
* **Exit code 2** is your mistake (bad name, bad value, missing file). Fix the input and retry.
  **Exit code 1** is a kankuro bug: `error.traceback` and `<project>/build/blender.log` explain it.
* **State lives in `character.json`.** Commands are idempotent edits of it. `kankuro show` prints it.
  Nothing is hidden in a cache or a session.
* **Discover, don't guess.** `kankuro --help` and `kankuro <command> --help` (options plus worked
  examples), `kankuro guide` (this guide; `kankuro guide --list` for the CLI reference, spec format
  and texture guide), `kankuro schema` (all commands as JSON), `kankuro catalog` (presets, sliders,
  hair, garments, fabrics, colours), `kankuro morphs --search <text>`, `kankuro animations`.
* **Look at your work.** `kankuro render` writes PNGs. An agent that can read images should open
  `renders/render_sheet.png` after visible changes.

## A good loop

```text
1. kankuro guide; kankuro catalog                  # learn the contract and what exists
2. kankuro init <dir> --preset <closest preset>
3. kankuro set ... / face ... / skin / eyes / brows / hair set ... / garment add ...  # rough pass from the brief
4. kankuro render                                   # look at render_sheet.png
5. compare with the brief; adjust with set / garment set; render again
   (use --focus head for faces, --animation Jog --frame 0.3 for clothing in motion)
6. kankuro build --animations <clips>; kankuro validate <glb>
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

Age slider values: 0.1875 ≈ 10 years, 0.5 = 25, 0.75 ≈ 57, 1.0 = 90.

## Textures need an image model, outside kankuro

kankuro never calls an image model and needs no API key. When a texture is needed:

1. `kankuro template <garment>` gives `<id>_template.png` and `<id>_mask.png`.
2. Hand the template to whatever image model you have, with a prompt from
   [codex-textures.md](codex-textures.md). Keep the output the same size and layout.
3. `kankuro garment set <id> --texture <png>` (plus `--height <png>` for relief).
4. `kankuro render --views front,back` and check it.

If no image model is available, a plain `--color` with a `--fabric` preset still looks like cloth.

## Common mistakes

| mistake | result | fix |
|---|---|---|
| `kankuro build -p ./hero` | `bad_arguments` | `-p` goes before the command: `kankuro -p ./hero build` |
| unquoted morph name | the shell treats `|` as a pipe | quote the whole assignment |
| `--color #ff0000` unquoted in some shells | `#` starts a comment, colour missing | `--color "#ff0000"` |
| two tops without `--keep-slot` | the first is replaced (see `replaced`) | add `--keep-slot` to layer them |
| `set hair.style=bob` | `bad_path` | `kankuro hair set bob` |
| `--animations all` on every build | big, slow GLB | list the clips you need |

## Performance

Spec commands are instant. `render` and `build` start Blender inside the process and take roughly
5 to 20 seconds each on a laptop CPU; renders scale with `--size` and `--samples`. Commands are
independent processes, so separate projects can be built in parallel.

## System prompt snippet

```text
You can build rigged 3D characters with the `kankuro` CLI.
- Every command prints one JSON object. Check "ok"; on failure read error.code and error.hint and fix the input.
- Start with `kankuro guide` and `kankuro catalog`; `kankuro <command> --help` shows options and examples.
  Never guess names; use `catalog`, `morphs --search`, `face list`, `animations`.
- A project is a folder with character.json. Create it with `kankuro init <dir> --preset <preset>`.
  Put -p <dir> BEFORE the command, or cd into the folder.
- Shape with `kankuro set body.macros.<slider>=<0..1>` and `body.height_cm=<cm>`; quote morph names: "body.morphs.<name>=<v>".
- Face: every character needs its own face. Use `kankuro face preset <archetype>`, `kankuro face randomize --seed N`
  and `kankuro face set <group.slider>=<-1..1>` (`kankuro face list`). Eyes: `kankuro eyes --color <name|#hex> tilt=..`.
  Eyebrows: `kankuro brows --preset <name> --color <name|#hex>`. Skin: `kankuro skin --color <name|#hex>`.
- Hair: `kankuro hair set <style> --color "#hex"`. Clothes: `kankuro garment add <type> --color "#hex" [--fabric name]`.
- After visible changes run `kankuro render` and look at renders/render_sheet.png. Use --focus head for faces.
- Custom fabric prints: `kankuro template <id>`, get the image painted on that template outside kankuro,
  then `kankuro garment set <id> --texture <png>`.
- Finish with `kankuro build --animations Idle_A,Walk` and `kankuro validate <glb>`; report the GLB path and any warnings.
```
