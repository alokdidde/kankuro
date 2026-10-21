"""Help text for `kankuro --help` and `kankuro <command> --help`, written for AI agents.

Each command has a one-line summary (shown in the command list), a description, and examples.
`{name}` placeholders are filled from the catalogs at runtime so the lists never go stale.
"""

TOP_DESCRIPTION = """\
kankuro: build rigged, game-ready 3D humans from the command line. Made for AI agents.

Every command except --help and `guide` prints exactly ONE JSON object on stdout:
  {"ok": true, "command": "...", ...}                         success, exit 0
  {"ok": false, "error": {"code", "message", "hint"}}         bad input, exit 2 (read the hint)
  {"ok": false, "error": {"code": "internal", "traceback"}}   bug, exit 1 (see build/blender.log)
A project is a folder holding character.json. Global options (-p) go BEFORE the command."""

TOP_EPILOG = """\
quick start:
  kankuro init ./hero --preset athletic_male
  kankuro -p ./hero set body.height_cm=183 skin.color=tan
  kankuro -p ./hero hair set short --color dark_brown
  kankuro -p ./hero garment add tshirt --color "#eeeeee"
  kankuro -p ./hero garment add pants
  kankuro -p ./hero render                      # then look at hero/renders/render_sheet.png
  kankuro -p ./hero build --animations Idle_A,Walk
  kankuro validate hero/build/hero.glb

learn more from the terminal:
  kankuro guide              how to drive kankuro as an agent (start here)
  kankuro guide --list       all guide topics (cli reference, spec format, textures, ...)
  kankuro <command> --help   options and examples for one command
  kankuro schema             machine-readable command summary (JSON)
  kankuro catalog            every valid preset, slider, hair style, garment, fabric, colour (JSON)

environment: KANKURO_PROJECT (default project dir), KANKURO_COMPACT=1 (one-line JSON)."""

COMMANDS = {
    "init": dict(
        summary="create a project folder with character.json",
        description="Create a project: a folder holding character.json. Everything about the character "
                    "lives in that file; files you add later are copied into <dir>/assets/.",
        examples="""\
  kankuro init ./ava --preset athletic_female --name Ava
  kankuro init ./hero --preset male --force       # overwrite an existing spec
presets: {presets}""",
        args={"dir": "folder to create (may already exist)",
              "preset": "starting body (default neutral): {presets}",
              "name": "character name; also the GLB file name (default: folder name)",
              "force": "overwrite an existing character.json"}),
    "show": dict(
        summary="print the spec and the last build manifest",
        description="Print character.json (validated) and, if there was a build, build/manifest.json.",
        examples="  kankuro -p ./hero show", args={}),
    "set": dict(
        summary="edit spec values: body sliders, morphs, height, skin, eyes, name",
        description="Set one or more values in character.json. Values are parsed as JSON when possible "
                    "(0.6, 183, true, null); null resets a value. Quote assignments that contain | or #.",
        examples="""\
  kankuro set body.macros.gender=0.9 body.macros.muscle=0.7 body.height_cm=183
  kankuro set skin.color=#8d5524 eyes.iris_color=hazel
  kankuro set "body.morphs.nose/nose-scale-horiz-decr|incr=0.4"
  kankuro set face.shape.nose.width=0.4
  kankuro set body.height_cm=null
settable paths:
  body.macros.<slider>  0..1: {sliders}
  body.morphs.<name>    see `kankuro morphs --search TEXT`
  face.shape.<slider>   see `kankuro face list`
  body.preset, body.height_cm, skin.*, eyes.iris_color, face.blendshapes, export.*, name
  (hair and clothes have their own commands)""",
        args={"assignments": "one or more PATH=VALUE"}),
    "catalog": dict(
        summary="list presets, sliders, hair styles, garments, fabrics, colours, expressions",
        description="Print what exists. Use it instead of guessing names.",
        examples="""\
  kankuro catalog
  kankuro catalog garments
  kankuro catalog colors
sections: {catalog_sections}""",
        args={"section": "print only this section"}),
    "morphs": dict(
        summary="list the 238 detailed MakeHuman morphs (face, torso, limbs)",
        description="List detailed morph modifiers for `set body.morphs.<name>=<value>`. Names with a "
                    "pair like decr|incr take -1..1 (negative = first word); single-sided ones 0..1. "
                    "For faces prefer the friendlier `kankuro face` sliders.",
        examples="""\
  kankuro morphs --group nose
  kankuro morphs --search jaw
  kankuro set "body.morphs.chin/chin-prominent-decr|incr=0.3\"""",
        args={"group": "only this group (armslegs, breast, cheek, chin, ears, eyes, head, mouth, neck, nose, torso, ...)",
              "search": "only names containing this text"}),
    "skin": dict(
        summary="skin tone, a painted skin texture, eyebrow colour",
        description="Whole-body skin tone (hex or a skin colour name) or a PNG painted on the body UV "
                    "layout (`kankuro template body`).",
        examples="""\
  kankuro skin --color tan
  kankuro skin --color "#c68e6b" --brow-color dark_brown
  kankuro skin --texture ./skin_painted.png
  kankuro skin --texture ""                       # remove the texture
skin colour names: {skin_colors}""",
        args={"color": "skin tone: #RRGGBB or a skin colour name",
              "texture": "PNG on the body UV template; \"\" removes it",
              "brow_color": "eyebrow colour: #RRGGBB or a hair colour name"}),
    "face": dict(
        summary="face shape: sliders, archetype presets, random faces",
        description="Friendly symmetric face sliders (head, forehead, brows, eyes, nose, mouth, jaw, "
                    "chin, cheeks, ears, neck). Bipolar sliders run -1..1 (about ±0.3 subtle, ±0.6 clear, "
                    "±1 extreme); head.* shape blends run 0..1. 0 removes a slider.",
        examples="""\
  kankuro face list --group nose                   # sliders with ranges and meanings
  kankuro face set nose.width=0.4 jaw.width=-0.3 chin.cleft=0.4
  kankuro face preset angular
  kankuro face preset soft --amount 0.5 --add
  kankuro face randomize --seed 7 --strength 0.3
  kankuro face randomize --groups eyes,nose --seed 12
  kankuro face reset --groups nose
presets: {face_presets}
then check: kankuro render --focus head --views front,three_quarter,side""",
        args={"action": "list | set | preset | randomize | reset",
              "values": "set: SLIDER=VALUE ...; preset: one or more preset names",
              "group": "list: only this group",
              "groups": "randomize/reset: only these groups, comma-separated",
              "seed": "randomize: same seed = same face",
              "strength": "randomize: 0.3 subtle, 0.5 natural (default), 1 caricature",
              "amount": "preset: strength multiplier (default 1.0)",
              "add": "add to the current sliders instead of replacing them"}),
    "eyes": dict(
        summary="iris colour and eye shape",
        description="Iris colour plus the eyes.* face sliders, written with or without the prefix: "
                    "size, spacing, height, tilt, openness, width, lid_crease, lid_fold, monolid, bags.",
        examples="""\
  kankuro eyes --color hazel
  kankuro eyes tilt=0.4 monolid=0.5 size=0.2
eye colour names: {eye_colors}""",
        args={"values": "eye shape sliders, SLIDER=VALUE (-1..1)",
              "color": "iris colour: #RRGGBB or an eye colour name"}),
    "brows": dict(
        summary="eyebrow hair shape and colour, brow ridge",
        description="Eyebrows are hair strands; shape them with a preset and/or the four shape options. "
                    "SLIDER=VALUE sets the brow ridge face sliders: height, tilt, ridge.",
        examples="""\
  kankuro brows --preset arched --color dark_brown
  kankuro brows --thickness 1.3 --arch -0.5 ridge=0.3
  kankuro brows --color hair                      # follow the hair colour (default)
  kankuro brows --off
presets: {brow_presets}""",
        args={"values": "brow ridge sliders: height=, tilt=, ridge= (-1..1)",
              "preset": "set all four shape values from a preset",
              "color": "#RRGGBB, a hair colour name, or hair (follow the hair colour)",
              "thickness": "band height 0.3..2.0: 0.5 thin, 1 natural, 1.6 bushy",
              "arch": "-1 flat .. 0 natural .. 1 high arch",
              "density": "hair count 0.2..2.0: 0.4 sparse, 1 natural, 1.6 dense",
              "length": "tail length 0.5..1.4: 0.7 short, 1.2 long",
              "on": "eyebrows on", "off": "eyebrows off"}),
    "hair": dict(
        summary="hair style and colour, or your own hair mesh",
        description="Procedural styles are grown from the current scalp, so they fit any head. "
                    "`hair set --color X` alone recolours the current hair.",
        examples="""\
  kankuro hair set ponytail --color dark_brown
  kankuro hair set --color auburn                  # recolour only
  kankuro hair import --file braids.glb --color "#2a1a10"
  kankuro hair remove
styles: {hair_styles}
hair colour names: {hair_colors}""",
        args={"action": "set | import | remove",
              "style": "set: a style name",
              "color": "#RRGGBB or a hair colour name",
              "texture": "optional PNG texture for the hair",
              "file": "import: your hair mesh (.glb/.gltf/.obj/.fbx) modelled on `kankuro reference-body`"}),
    "garment": dict(
        summary="add, import, change or remove clothes",
        description="Each garment type has a slot; `add` replaces whatever is in that slot (see `replaced` "
                    "in the output) unless --keep-slot. Outer layers are fitted over inner ones and the skin "
                    "underneath is hidden. Every garment gets fabric relief (weave, stitching, folds).",
        examples="""\
  kankuro garment add tshirt --color "#eeeeee"
  kankuro garment add tanktop --keep-slot          # layer under the T-shirt
  kankuro garment add jacket --color "#556b2f" --fabric denim
  kankuro garment set jacket --texture ./camo.png --height ./camo_height.png
  kankuro garment import --file hat.glb --id hat --color "#6b4f2a"
  kankuro garment remove jacket
types: {garments}
fabrics: {fabrics}
custom prints: `kankuro template <id>`, paint it outside kankuro, then `garment set <id> --texture <png>`
(`kankuro guide textures` has image-model prompts)""",
        args={"action": "add | import | set | remove",
              "type": "add: garment type; set/remove: garment id",
              "id": "id to give it (needed to add two of one type); or the id for set/remove",
              "file": "import: your mesh modelled on `kankuro reference-body`",
              "color": "base colour: #RRGGBB or a colour name",
              "texture": "albedo PNG painted on the garment's UV template; \"\" removes it",
              "layer": "stacking order override (higher = further out)",
              "roughness": "material roughness",
              "hide_body": "false keeps the skin under this garment",
              "normal_strength": "scale for the final normal map (default 1.0)",
              "keep_slot": "don't replace the garment already in this slot"}),
    "template": dict(
        summary="write UV template + mask PNGs for repainting garments or skin",
        description="For each target writes <id>_template.png (flat sketch: left half = front, right half "
                    "= back seen from behind) and <id>_mask.png (white where the texture is used). One "
                    "texture fits that garment type on every body shape.",
        examples="""\
  kankuro template tshirt
  kankuro template body --size 4096
  kankuro template all""",
        args={"targets": "garment ids, garment types, body, or all (default all)",
              "out": "output folder (default <project>/templates)",
              "size": "image size in pixels (default 2048)"}),
    "build": dict(
        summary="build and export the rigged GLB (+ manifest)",
        description="Exports body, eyes, hair and garments as skinned meshes on the Mesh2Motion skeleton "
                    "(T-pose rest), PBR materials, ARKit 52 facial blendshapes, and the chosen animation "
                    "clips. Writes build/manifest.json; read its `warnings`.",
        examples="""\
  kankuro build
  kankuro build --animations Idle_A,Walk,Jog
  kankuro build --out ./out/hero.glb --render
then: kankuro validate build/<name>.glb""",
        args={"out": "output GLB (default <project>/build/<name>.glb)",
              "animations": "Mesh2Motion clips, comma-separated, or all (see `kankuro animations`)",
              "render": "also render preview views",
              "size": "preview image height (with --render)",
              "samples": "preview Cycles samples (with --render)"}),
    "render": dict(
        summary="preview PNGs (views, head close-up, animation pose, expression)",
        description="Renders with Cycles on the CPU and writes one PNG per view plus <prefix>_sheet.png. "
                    "Look at the sheet after every visible change.",
        examples="""\
  kankuro render
  kankuro render --focus head --views front,three_quarter
  kankuro render --animation Jog --frame 0.3       # clothes mid-stride
  kankuro render --focus head --expression smile
  kankuro render --expression "jawOpen=0.6,eyeBlinkLeft=1"
  kankuro render --size 384 --samples 8            # faster while iterating""",
        args={"views": "comma-separated: front, three_quarter, side, back (default all four)",
              "focus": "full (default), upper, or head",
              "animation": "pose from a Mesh2Motion clip",
              "frame": "with --animation: 0..1 = fraction of the clip, >1 = frame number",
              "expression": "preset ({expressions}) and/or ARKit weights like jawOpen=0.6",
              "size": "image height in pixels (default 512)",
              "samples": "Cycles samples (default 12)",
              "out": "output folder (default <project>/renders)",
              "prefix": "file name prefix"}),
    "animations": dict(
        summary="list the Mesh2Motion animation clips",
        description="Clips for `build --animations` and `render --animation`. Names ending in _RM have root motion.",
        examples="  kankuro animations", args={}),
    "reference-body": dict(
        summary="export the neutral body to model custom hair/garments on",
        description="Model on top of this body in any 3D tool, then `hair import` / `garment import`; the "
                    "mesh is conformed and skinned to every body shape.",
        examples="  kankuro reference-body --out ref.glb\n  kankuro reference-body --out ref_rigged.glb --with-rig",
        args={"out": "output GLB", "with_rig": "include the skeleton and skin weights"}),
    "autorig": dict(
        summary="rig any humanoid mesh to the Mesh2Motion skeleton",
        description="Upright humanoids in T- or A-pose, dressed or not, realistic or cartoon. Legs must be "
                    "separate below the knees. Models taller than 20 units are taken as centimetres. "
                    "No project needed.",
        examples="""\
  kankuro autorig knight.glb --out knight_rigged.glb
  kankuro autorig robot.fbx --out robot.glb --animations Idle_A,Walk --render ./check""",
        args={"mesh": "input .glb, .gltf, .obj or .fbx",
              "out": "output GLB",
              "facing": "which way the model faces (default auto, detected from the feet)",
              "animations": "clips to bake in, comma-separated",
              "render": "folder for check renders (rest and posed)",
              "method": "skinning: auto (heat, then fallbacks), heat, proximity"}),
    "validate": dict(
        summary="check a GLB against the Mesh2Motion human standard",
        description="Checks bone names, hierarchy, rest orientations, T-pose and skin weights. Any check "
                    "with \"pass\": false says what is off.",
        examples="  kankuro validate build/hero.glb", args={"glb": "the GLB to check"}),
    "schema": dict(
        summary="machine-readable summary of every command (JSON)",
        description="Commands, the spec file name and conventions as JSON.",
        examples="  kankuro schema", args={}),
    "guide": dict(
        summary="print a usage guide (agents, cli reference, spec, textures, ...)",
        description="Print a guide as plain Markdown text. With no topic it prints the agent guide: the "
                    "JSON contract, a good working loop, and a system prompt snippet.",
        examples="""\
  kankuro guide                  # the agent guide
  kankuro guide cli              # full CLI reference
  kankuro guide --list
  kankuro guide spec --json      # wrapped in the usual JSON object""",
        args={"topic": "guide to print (default agents); see --list",
              "list": "list the topics (JSON)",
              "json": "print {\"ok\": true, \"text\": ...} instead of plain text"}),
}


def fill(text, names):
    try:
        return text.format(**names)
    except (KeyError, IndexError, ValueError):
        return text


def names():
    """Live catalog lists for the {placeholders}. Must stay bpy-free."""
    from . import catalog, morph, spec
    out = {"presets": ", ".join(spec.PRESETS), "sliders": ", ".join(morph.MACROS),
           "hair_styles": ", ".join(catalog.HAIR_STYLES), "garments": ", ".join(catalog.GARMENTS)}
    try:
        from . import fabric
        out["fabrics"] = ", ".join(fabric.FABRICS) + ", none"
    except Exception:
        pass
    try:
        from . import face
        out["expressions"] = ", ".join(face.PRESETS)
    except Exception:
        pass
    try:
        from . import appearance
        out["face_presets"] = ", ".join(appearance.FACE_PRESETS)
        out["brow_presets"] = ", ".join(appearance.BROW_PRESETS)
        out["skin_colors"] = ", ".join(appearance.SKIN_TONES)
        out["hair_colors"] = ", ".join(appearance.HAIR_COLORS)
        out["eye_colors"] = ", ".join(appearance.EYE_COLORS)
    except Exception:
        pass
    out["catalog_sections"] = ("presets, body_sliders, hair_styles, garments, fabrics, face_sliders, "
                               "face_presets, colors, brows, expressions")
    return out
