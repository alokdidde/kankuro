"""Help text for `sasori --help` and `sasori <command> --help`, written for AI agents.

Each command has a one-line summary (shown in the command list), a description, and examples.
`{name}` placeholders are filled from the catalogs at runtime so the lists never go stale.
"""

TOP_DESCRIPTION = """\
sasori: build rigged, game-ready 3D humans from the command line. Made for AI agents.

Every command except --help and `guide` prints exactly ONE JSON object on stdout:
  {"ok": true, "command": "...", ...}                         success, exit 0
  {"ok": false, "error": {"code", "message", "hint"}}         bad input, exit 2 (read the hint)
  {"ok": false, "error": {"code": "internal", "traceback"}}   bug, exit 1 (see build/blender.log)
A project is a folder holding character.json. Global options (-p) go BEFORE the command."""

TOP_EPILOG = """\
quick start:
  sasori init ./hero --preset athletic_male
  sasori -p ./hero set body.height_cm=183 skin.color=tan
  sasori -p ./hero hair set short --color dark_brown
  sasori -p ./hero garment add tshirt --color "#eeeeee"
  sasori -p ./hero garment add pants
  sasori -p ./hero render                      # then look at hero/renders/render_sheet.png
  sasori -p ./hero build --animations Idle_A,Walk
  sasori validate hero/build/hero.glb

facial rig: every GLB carries the 52 ARKit blendshapes on the body (see `sasori build --help`);
  preview them with `sasori render --focus head --expression smile`.

learn more from the terminal:
  sasori guide              how to drive sasori as an agent (start here)
  sasori guide --list       all guide topics (cli reference, spec format, textures, ...)
  sasori <command> --help   options and examples for one command
  sasori schema             machine-readable command summary (JSON)
  sasori catalog            every valid preset, slider, hair style, garment, fabric, colour (JSON)

environment: SASORI_PROJECT (default project dir), SASORI_COMPACT=1 (one-line JSON)."""

COMMANDS = {
    "init": dict(
        summary="create a project folder with character.json",
        description="Create a project: a folder holding character.json. Everything about the character "
                    "lives in that file; files you add later are copied into <dir>/assets/.",
        examples="""\
  sasori init ./ava --preset athletic_female --name Ava
  sasori init ./hero --preset male --force       # overwrite an existing spec
presets: {presets}""",
        args={"dir": "folder to create (may already exist)",
              "preset": "starting body (default neutral): {presets}",
              "name": "character name; also the GLB file name (default: folder name)",
              "force": "overwrite an existing character.json"}),
    "show": dict(
        summary="print the spec and the last build manifest",
        description="Print character.json (validated) and, if there was a build, build/manifest.json.",
        examples="  sasori -p ./hero show", args={}),
    "set": dict(
        summary="edit spec values: body sliders, morphs, height, skin, eyes, name",
        description="Set one or more values in character.json. Values are parsed as JSON when possible "
                    "(0.6, 183, true, null); null resets a value. Quote assignments that contain | or #.",
        examples="""\
  sasori set body.macros.gender=0.9 body.macros.muscle=0.7 body.height_cm=183
  sasori set skin.color=#8d5524 eyes.iris_color=hazel
  sasori set "body.morphs.nose/nose-scale-horiz-decr|incr=0.4"
  sasori set face.shape.nose.width=0.4
  sasori set body.height_cm=null
settable paths:
  body.macros.<slider>  0..1: {sliders}
  body.morphs.<name>    see `sasori morphs --search TEXT`
  face.shape.<slider>   see `sasori face list`
  body.preset, body.height_cm, skin.*, eyes.iris_color, face.blendshapes, export.*, name
  (hair and clothes have their own commands)""",
        args={"assignments": "one or more PATH=VALUE"}),
    "catalog": dict(
        summary="list presets, sliders, hair styles, garments, fabrics, colours, expressions",
        description="Print what exists. Use it instead of guessing names.",
        examples="""\
  sasori catalog
  sasori catalog garments
  sasori catalog colors
  sasori catalog expressions      # the 52 ARKit blendshape names + expression presets
sections: {catalog_sections}""",
        args={"section": "print only this section"}),
    "morphs": dict(
        summary="list the 238 detailed MakeHuman morphs (face, torso, limbs)",
        description="List detailed morph modifiers for `set body.morphs.<name>=<value>`. Names with a "
                    "pair like decr|incr take -1..1 (negative = first word); single-sided ones 0..1. "
                    "For faces prefer the friendlier `sasori face` sliders.",
        examples="""\
  sasori morphs --group nose
  sasori morphs --search jaw
  sasori set "body.morphs.chin/chin-prominent-decr|incr=0.3\"""",
        args={"group": "only this group (armslegs, breast, cheek, chin, ears, eyes, head, mouth, neck, nose, torso, ...)",
              "search": "only names containing this text"}),
    "skin": dict(
        summary="skin tone, a painted skin texture, eyebrow colour",
        description="Whole-body skin tone (hex or a skin colour name) or a PNG painted on the body UV "
                    "layout (`sasori template body`).",
        examples="""\
  sasori skin --color tan
  sasori skin --color "#c68e6b" --brow-color dark_brown
  sasori skin --texture ./skin_painted.png
  sasori skin --texture ""                       # remove the texture
  sasori skin --detail false                     # flat tone: no cheek/lid variation, cavity shading or oily T-zone
skin colour names: {skin_colors}""",
        args={"color": "skin tone: #RRGGBB or a skin colour name",
              "detail": "true (default): natural tone variation (warmer cheeks and nose, darker lids and lash "
                        "lines), baked cavity shading and a T-zone roughness map, with shading tuned to the "
                        "tone; false: one flat tone",
              "texture": "PNG on the body UV template; \"\" removes it",
              "brow_color": "eyebrow colour: #RRGGBB or a hair colour name"}),
    "face": dict(
        summary="face shape: sliders, archetype presets, random faces",
        description="Friendly symmetric face sliders (head, forehead, brows, eyes, nose, mouth, jaw, "
                    "chin, cheeks, ears, neck). Bipolar sliders run -1..1 (about ±0.3 subtle, ±0.6 clear, "
                    "±1 extreme); head.* shape blends run 0..1. 0 removes a slider.",
        examples="""\
  sasori face list --group nose                   # sliders with ranges and meanings
  sasori face set nose.width=0.4 jaw.width=-0.3 chin.cleft=0.4
  sasori face preset angular
  sasori face preset soft --amount 0.5 --add
  sasori face randomize --seed 7 --strength 0.3
  sasori face randomize --groups eyes,nose --seed 12
  sasori face reset --groups nose
presets: {face_presets}
then check: sasori render --focus head --views front,three_quarter,side
(face *shape* only; facial *expressions* are the ARKit blendshapes, see `sasori render --help`)""",
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
  sasori eyes --color hazel
  sasori eyes tilt=0.4 monolid=0.5 size=0.2
eye colour names: {eye_colors}""",
        args={"values": "eye shape sliders, SLIDER=VALUE (-1..1)",
              "color": "iris colour: #RRGGBB or an eye colour name"}),
    "brows": dict(
        summary="eyebrow hair shape and colour, brow ridge",
        description="Eyebrows are hair strands; shape them with a preset and/or the four shape options. "
                    "SLIDER=VALUE sets the brow ridge face sliders: height, tilt, ridge.",
        examples="""\
  sasori brows --preset arched --color dark_brown
  sasori brows --thickness 1.3 --arch -0.5 ridge=0.3
  sasori brows --color hair                      # follow the hair colour (default)
  sasori brows --off
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
  sasori hair set ponytail --color dark_brown
  sasori hair set --color auburn                  # recolour only
  sasori hair import --file braids.glb --color "#2a1a10"
  sasori hair remove
styles: {hair_styles}
hair colour names: {hair_colors}""",
        args={"action": "set | import | remove",
              "style": "set: a style name",
              "color": "#RRGGBB or a hair colour name",
              "texture": "optional PNG texture for the hair",
              "file": "import: your hair mesh (.glb/.gltf/.obj/.fbx) modelled on `sasori reference-body`"}),
    "garment": dict(
        summary="add, import, change or remove clothes",
        description="Each garment type has a slot; `add` replaces whatever is in that slot (see `replaced` "
                    "in the output) unless --keep-slot. Outer layers are fitted over inner ones and the skin "
                    "underneath is hidden. Every garment gets fabric relief (weave, stitching, folds).",
        examples="""\
  sasori garment add tshirt --color "#eeeeee"
  sasori garment add tanktop --keep-slot          # layer under the T-shirt
  sasori garment add jacket --color "#556b2f" --fabric denim
  sasori garment set jacket --texture ./camo.png --height ./camo_height.png
  sasori garment import --file hat.glb --id hat --color "#6b4f2a"
  sasori garment set saree --material-region border=gold_zari    # gold zari border on the saree
  sasori garment set kurta --material-region trim=silver --mask ./kurta_trim_mask.png
  sasori garment import --file armour.glb --id kavach --material bronze
  sasori garment remove jacket
types: {garments}
fabrics: {fabrics}
materials: {materials}  (`sasori catalog materials` lists their values)
custom prints: `sasori template <id>`, paint it outside sasori, then `garment set <id> --texture <png>`
(`sasori guide textures` has image-model prompts)""",
        args={"action": "add | import | set | remove",
              "type": "add: garment type; set/remove: garment id",
              "id": "id to give it (needed to add two of one type); or the id for set/remove",
              "file": "import: your mesh modelled on `sasori reference-body`",
              "color": "base colour: #RRGGBB or a colour name",
              "texture": "albedo PNG painted on the garment's UV template; \"\" removes it",
              "layer": "stacking order override (higher = further out)",
              "roughness": "material roughness",
              "hide_body": "false keeps the skin under this garment",
              "normal_strength": "scale for the final normal map (default 1.0)",
              "material": "material preset for the whole garment (gold, bronze, steel...) or none; without "
                          "--color the preset's own colour is used",
              "material_region": "NAME=PRESET[:#RRGGBB] a region of the UV template in another material "
                                 "(border, hem, or any name with --mask); PRESET none removes it; repeatable",
              "mask": "greyscale PNG on the garment's UV template, white = in the region",
              "keep_slot": "don't replace the garment already in this slot"}),
    "accessory": dict(
        summary="rigid crowns, earrings, necklaces, armlets, bangles on one bone",
        description="An accessory keeps its shape and follows one bone (or a short hanging chain with "
                    "--hang). It is modelled on `sasori reference-body` and carried onto any body shape. "
                    "--fit settles it: none (rigid; slides along the bone until clear, so a crown rides up "
                    "a bigger head), wrap (radial scale to hug a limb), chest/neck (the lower part settles "
                    "onto the chest or the clothes), pierce (rigid, through the body: earrings). Accessories sit over garments; a band round the head "
                    "presses the hair under it.",
        examples="""\
  sasori accessory add circlet                          # a built-in (see list)
  sasori accessory add crown --file crown.glb --bone head --material gold
  sasori accessory add kundal_l --file earring.glb --bone head --hang 2
  sasori accessory add haar --file necklace.glb --bone spine_03 --hang 3 --fit chest --material gold
  sasori accessory add bajuband_l --file armlet.glb --bone upperarm_l --fit wrap
  sasori accessory set crown --offset 0,0,0.01 --rotate 0,0,5 --scale 1.05
  sasori accessory remove crown
  sasori accessory list
built-ins: {accessories}""",
        args={"action": "add | set | remove | list",
              "id": "the accessory's id (also its mesh name in the GLB); add <built-in name> uses that built-in",
              "file": "mesh modelled on the reference body", "builtin": "a built-in accessory",
              "bone": "the Mesh2Motion bone it follows", "fit": "none | wrap | chest | neck | pierce",
              "hang": "extra bones for a dangling part (they swing on clips)",
              "offset": "x,y,z metres (x = character's left, y = back, z = up)",
              "rotate": "x,y,z degrees about its centre", "scale": "uniform scale",
              "material": "material preset (`catalog materials`) or none", "color": "base colour",
              "roughness": "roughness override", "layer": "stacking (default 10, over every garment)",
              "hide_hair": "press hair under a band round the head (default true on the head bone)"}),
    "prop": dict(
        summary="objects held in the hand, with a grip pose",
        description="A prop is rigid and hangs from a socket bone (prop_l / prop_r) under the hand. Its "
                    "grip is a finger pose baked over every clip's finger channels; contact grips curl each "
                    "finger until it touches the prop. --hand both keeps the other hand on the prop with "
                    "IK and reports clips it can't reach in `warnings`.",
        examples="""\
  sasori prop add staff                                 # built-in walking staff in the right hand
  sasori prop add bow --file bow.glb --hand l --grip power
  sasori prop add flute --hand both --anchor r --grip flute
  sasori prop set bow --offset 0,0.02,0 --rotate 0,90,0
  sasori render --animation Walk --frame 0.3 --views front,side
  sasori prop remove bow
built-ins: {props}
grips: {grips}""",
        args={"action": "add | set | remove | list", "id": "the prop's id; add <built-in name> uses that built-in",
              "file": "mesh modelled on the reference body, held in the T-posed hand",
              "builtin": "a built-in prop", "hand": "l | r | both", "anchor": "both: the hand that holds it",
              "grip": "finger pose (`grip list`)", "grip_weight": "0..1 blend over the clip's fingers",
              "reach": "both: where the other hand holds, metres along the prop from the grip towards the index "
                       "finger (negative: towards the little finger; default -0.3)",
              "offset": "x,y,z metres", "rotate": "x,y,z degrees about the grip", "scale": "uniform scale",
              "material": "material preset or none", "color": "base colour", "roughness": "roughness override"}),
    "grip": dict(
        summary="list the finger poses for props",
        description="Contact grips curl each finger joint until it touches the prop; the others are fixed poses.",
        examples="  sasori grip list",
        args={"action": "list"}),
    "bones": dict(
        summary="extra bone chains: tails, braids, dangling ornaments",
        description="An extra chain hangs under a standard bone and never changes the 65 Mesh2Motion bones, "
                    "so clips still play. `build` and `render` bake its follow-through (a damped spring "
                    "with gravity, kept out of the legs) into every clip; it loops cleanly. With --radius "
                    "the chain gets a tapered tube mesh (a tail); --follow hair takes over the hanging hair "
                    "(a braid or ponytail).",
        examples="""\
  sasori bones add tail --parent pelvis --count 8 --length 0.9 --curve up:0.3 --taper 0.5 --radius 0.035
  sasori bones add braid --parent head --count 5 --follow hair
  sasori bones list
  sasori bones remove tail
  sasori build --animations Idle_A,Walk --secondary-motion tail,braid""",
        args={"action": "add | set | remove | list", "id": "chain id; bones are <id>_01, <id>_02, ...",
              "parent": "the standard bone it hangs from", "count": "number of bones (1..32)",
              "length": "total length in metres", "taper": "0..1: how much shorter/thinner towards the tip",
              "curve": "up:F or down:F, how far the chain bends along its length (1 = half a turn)",
              "radius": "radius of the tube mesh (0 = no mesh)", "color": "tube colour (default: hair colour)",
              "material": "tube material preset", "follow": "hair: bind the hanging hair to the chain",
              "stiffness": "spring back to the rest shape (default 0.35)", "damping": "default 0.25",
              "gravity": "default 1.0", "no_motion": "keep it rigid in clips (no follow-through)"}),
    "template": dict(
        summary="write UV template + mask PNGs for repainting garments or skin",
        description="For each target writes <id>_template.png (flat sketch: left half = front, right half "
                    "= back seen from behind) and <id>_mask.png (white where the texture is used), plus "
                    "<id>_border_mask.png and <id>_hem_mask.png (the built-in material regions). One "
                    "texture fits that garment type on every body shape.",
        examples="""\
  sasori template tshirt
  sasori template body --size 4096
  sasori template all""",
        args={"targets": "garment ids, garment types, body, or all (default all)",
              "out": "output folder (default <project>/templates)",
              "size": "image size in pixels (default 2048)"}),
    "build": dict(
        summary="build and export the rigged GLB (+ manifest)",
        description="Exports body, eyes, hair and garments as skinned meshes on the Mesh2Motion skeleton "
                    "(T-pose rest), PBR materials, ARKit 52 facial blendshapes, and the chosen animation "
                    "clips. Writes build/manifest.json; read its `warnings`.",
        examples="""\
  sasori build
  sasori build --animations Idle_A,Walk,Jog
  sasori build --out ./out/hero.glb --render
  sasori build --animations Idle_A,Walk --secondary-motion tail,braid
  sasori set face.blendshapes=none && sasori build   # leave out the facial rig (smaller file)
then: sasori validate build/<name>.glb
facial rig: the Body mesh carries the 52 ARKit blendshapes (jawOpen, eyeBlinkLeft, mouthSmileRight, ...)
as named glTF morph targets at weight 0, ready for ARKit / Live Link / three.js face tracking.
List them with `sasori catalog expressions`; preview with `sasori render --expression`.""",
        args={"out": "output GLB (default <project>/build/<name>.glb)",
              "animations": "Mesh2Motion clips, comma-separated, or all (see `sasori animations`)",
              "render": "also render preview views",
              "size": "preview image height (with --render)",
              "samples": "preview Cycles samples (with --render)",
              "secondary_motion": "extra bone chains whose follow-through is baked into the clips: all "
                                  "(default), none, or chain ids"}),
    "render": dict(
        summary="preview PNGs (views, head close-up, animation pose, expression)",
        description="Renders with Cycles on the CPU and writes one PNG per view plus <prefix>_sheet.png. "
                    "Look at the sheet after every visible change.",
        examples="""\
  sasori render
  sasori render --focus head --views front,three_quarter
  sasori render --animation Jog --frame 0.3       # clothes mid-stride
  sasori render --focus head --expression smile
  sasori render --expression "jawOpen=0.6,eyeBlinkLeft=1"
  sasori render --focus head --expression "smile,jawOpen=0.2"   # preset plus tweaks
  sasori render --size 384 --samples 8            # faster while iterating""",
        args={"views": "comma-separated: front, three_quarter, side, back_three_quarter, back (default front, three_quarter, side, back)",
              "focus": "full (default), upper, or head",
              "animation": "pose from a Mesh2Motion clip",
              "frame": "with --animation: 0..1 = fraction of the clip, >1 = frame number",
              "expression": "facial expression from the ARKit blendshapes: a preset ({expressions}), "
                            "NAME=WEIGHT pairs (0..1; names from `sasori catalog expressions`), or both, "
                            "comma-separated. Needs face.blendshapes=arkit52 (the default)",
              "size": "image height in pixels (default 512)",
              "samples": "Cycles samples (default 12)",
              "out": "output folder (default <project>/renders)",
              "prefix": "file name prefix",
              "secondary_motion": "with --animation: extra chains to simulate (all, none, or ids)"}),
    "animations": dict(
        summary="list the Mesh2Motion animation clips",
        description="Clips for `build --animations` and `render --animation`. Names ending in _RM have root motion.",
        examples="  sasori animations", args={}),
    "reference-body": dict(
        summary="export the neutral body to model custom hair/garments on",
        description="Model on top of this body in any 3D tool, then `hair import` / `garment import`; the "
                    "mesh is conformed and skinned to every body shape.",
        examples="  sasori reference-body --out ref.glb\n  sasori reference-body --out ref_rigged.glb --with-rig",
        args={"out": "output GLB", "with_rig": "include the skeleton and skin weights"}),
    "autorig": dict(
        summary="rig any humanoid mesh to the Mesh2Motion skeleton",
        description="Upright humanoids in T- or A-pose, dressed or not, realistic or cartoon. Legs must be "
                    "separate below the knees. Models taller than 20 units are taken as centimetres. "
                    "No project needed.",
        examples="""\
  sasori autorig knight.glb --out knight_rigged.glb
  sasori autorig robot.fbx --out robot.glb --animations Idle_A,Walk --render ./check
  sasori autorig vanara.glb --out vanara.glb --extra-chain tail:Tail:8 --animations Walk
  sasori autorig farmer.glb --out farmer.glb --prop staff --prop ./hoe.glb:l:power --animations Idle_A""",
        args={"mesh": "input .glb, .gltf, .obj or .fbx",
              "prop": "NAME[:HAND[:GRIP]]: a built-in prop or a mesh file put in the hand (repeatable)",
              "extra_chain": "ID:PART[:COUNT]: an extra bone chain through a mesh part or vertex group of the "
                             "file (a tail), with follow-through on the clips (repeatable)",
              "out": "output GLB",
              "facing": "which way the model faces (default auto, detected from the feet)",
              "animations": "clips to bake in, comma-separated",
              "render": "folder for check renders (rest and posed)",
              "method": "skinning: auto (heat, then fallbacks), heat, proximity"}),
    "validate": dict(
        summary="check a GLB against the Mesh2Motion human standard",
        description="Checks bone names, hierarchy, rest orientations, T-pose, skin weights, the toe pivot "
                    "(ball_at_toe_crease), and for files "
                    "with facial blendshapes that all 52 ARKit shapes are present (arkit_blendshapes) and rest "
                    "at weight 0 (blendshapes_at_rest). Any check with \"pass\": false says what is off.",
        examples="  sasori validate build/hero.glb", args={"glb": "the GLB to check"}),
    "schema": dict(
        summary="machine-readable summary of every command (JSON)",
        description="Commands, the spec file name and conventions as JSON.",
        examples="  sasori schema", args={}),
    "guide": dict(
        summary="print a usage guide (agents, cli reference, spec, textures, ...)",
        description="Print a guide as plain Markdown text. With no topic it prints the agent guide: the "
                    "JSON contract, a good working loop, and a system prompt snippet.",
        examples="""\
  sasori guide                  # the agent guide
  sasori guide cli              # full CLI reference
  sasori guide --list
  sasori guide spec --json      # wrapped in the usual JSON object""",
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
    from . import matlib
    out["materials"] = ", ".join(matlib.MATERIALS)
    out["accessories"] = ", ".join(catalog.ACCESSORIES)
    out["props"] = ", ".join(catalog.PROPS)
    out["grips"] = ", ".join(catalog.GRIPS)
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
