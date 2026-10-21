#!/bin/bash
# Eight characters built only with CLI commands, to show face/skin/hair/eye/brow variety.
# Usage: tools/face_variety.sh [WORK_DIR] [SHEET_PNG]   (run from the repo root, PYTHONPATH=.)
set -e
OUT=${1:-/tmp/faces}; SHEET=${2:-examples/face_variety.png}; mkdir -p "$OUT"
cc() { python3 -m ccreator -p "$P" "$@" > /dev/null; }
mk() { P="$OUT/$1"; python3 -m ccreator init "$P" --preset "$2" --force > /dev/null; }

mk f1 female;      cc set body.macros.african=0.8 body.macros.caucasian=0.1 body.macros.asian=0.1
cc face preset broad --amount 0.7; cc face randomize --seed 11 --strength 0.35 --add
cc skin --color dark_brown; cc hair set afro --color soft_black; cc eyes --color dark_brown; cc brows --preset natural

mk m1 male;        cc set body.macros.caucasian=0.9 body.macros.age=0.6
cc face preset angular; cc skin --color fair; cc hair set short --color ginger
cc eyes --color green tilt=-0.3; cc brows --preset thick

mk f2 female;      cc set body.macros.asian=0.9 body.macros.age=0.4
cc face preset soft; cc face set eyes.monolid=0.6 eyes.tilt=0.4 nose.projection=-0.3
cc skin --color light_olive; cc hair set bob --color blue_black; cc eyes --color brown; cc brows --preset straight

mk m2 male;        cc set body.macros.age=0.85 body.macros.weight=0.65
cc face preset rugged; cc skin --color medium; cc hair set short --color salt_pepper
cc eyes --color steel_blue; cc brows --preset bushy --color grey

mk f3 female;      cc face preset heart; cc face set eyes.size=0.4 mouth.upper_lip=0.4
cc skin --color porcelain; cc hair set long --color platinum; cc eyes --color light_blue; cc brows --preset arched --color light_brown

mk m3 male;        cc set body.macros.asian=0.5 body.macros.caucasian=0.5
cc face preset aquiline; cc skin --color tan; cc hair set ponytail --color dark_brown; cc eyes --color hazel; cc brows --preset natural

mk f4 female;      cc face randomize --seed 7 --strength 0.6; cc skin --color olive; cc hair set ponytail --color auburn
cc eyes --color amber; cc brows --preset thin

mk m4 male;        cc set body.macros.african=0.6 body.macros.caucasian=0.4
cc face randomize --seed 21 --strength 0.6; cc skin --color brown; cc hair set buzz --color black; cc eyes --color light_brown; cc brows --preset short

for c in f1 m1 f2 m2 f3 m3 f4 m4; do
  python3 -m ccreator -p "$OUT/$c" render --focus head --views front,three_quarter --size ${SIZE:-384} --samples ${SAMPLES:-16} > /dev/null
done
python3 - "$OUT" "$SHEET" <<'PY'
import sys
from PIL import Image
out, sheet = sys.argv[1:]
ims = [Image.open(f"{out}/{c}/renders/render_sheet.png") for c in "f1 m1 f2 m2 f3 m3 f4 m4".split()]
w, h = ims[0].size
s = Image.new("RGB", (w * 2, h * 4), "white")
for i, im in enumerate(ims):
    s.paste(im, ((i % 2) * w, (i // 2) * h))
s.save(sheet)
PY
