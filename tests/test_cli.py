"""End-to-end CLI tests. Run: python -m pytest tests -q   (or python -m unittest discover tests)"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cc(*args, project=None, ok=True):
    env = dict(os.environ, CCREATOR_COMPACT="1", PYTHONPATH=ROOT)
    cmd = [sys.executable, "-m", "ccreator"] + (["-p", project] if project else []) + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT)
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"stdout must be exactly one JSON line, got: {r.stdout!r} {r.stderr[-500:]}"
    out = json.loads(lines[0])
    if ok:
        assert out["ok"], out
    return out


class SpecCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p = os.path.join(self.tmp, "hero")
        cc("init", self.p, "--preset", "male")

    def test_set_and_errors(self):
        out = cc("set", "body.macros.weight=0.8", "skin.color=#8d5524", "body.height_cm=182", project=self.p)
        self.assertEqual(out["spec"]["body"]["height_cm"], 182)
        bad = cc("set", "body.macros.nope=1", project=self.p, ok=False)
        self.assertEqual(bad["error"]["code"], "unknown_macro")
        self.assertIn("hint", bad["error"])
        bad = cc("set", "skin.color=red", project=self.p, ok=False)
        self.assertEqual(bad["error"]["code"], "bad_color")

    def test_morph_listing(self):
        out = cc("morphs", "--search", "nose")
        self.assertGreater(out["count"], 5)
        name = out["modifiers"][0]["name"]
        cc("set", f"body.morphs.{name}=0.5", project=self.p)

    def test_garment_slots(self):
        cc("garment", "add", "tshirt", project=self.p)
        out = cc("garment", "add", "longsleeve", "--color", "#334455", project=self.p)
        self.assertEqual(out["replaced"], ["tshirt"])
        out = cc("garment", "add", "jacket", project=self.p)
        self.assertEqual(len(out["garments"]), 2)
        bad = cc("garment", "add", "cape", project=self.p, ok=False)
        self.assertEqual(bad["error"]["code"], "unknown_garment")

    def test_missing_project(self):
        out = cc("show", project=os.path.join(self.tmp, "nope"), ok=False)
        self.assertEqual(out["error"]["code"], "no_project")


class BuildCommands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.p = os.path.join(cls.tmp, "ava")
        cc("init", cls.p, "--preset", "athletic_female")
        cc("hair", "set", "long", "--color", "#2a1a10", project=cls.p)
        cc("garment", "add", "tanktop", "--color", "#c0392b", project=cls.p)
        cc("garment", "add", "skirt", "--color", "#2c3e50", project=cls.p)
        cc("garment", "add", "boots", project=cls.p)

    def test_build_validate(self):
        out = cc("build", "--animations", "Idle_A", project=self.p)
        self.assertTrue(os.path.exists(out["glb"]))
        self.assertEqual(out["skeleton"]["bones"], 66)
        self.assertEqual(out["animations"], ["Idle_A"])
        v = cc("validate", out["glb"])
        self.assertTrue(v["valid"], v["checks"])

    def test_templates_and_texture(self):
        out = cc("template", "tanktop", "body", "--size", "512", project=self.p)
        tpl = out["templates"]["tanktop"]
        self.assertTrue(os.path.exists(tpl["template"]) and os.path.exists(tpl["mask"]))
        cc("garment", "set", "tanktop", "--texture", tpl["template"], project=self.p)
        out = cc("render", "--views", "front", "--size", "128", "--samples", "2", project=self.p)
        self.assertTrue(os.path.exists(out["sheet"]))


    def test_fabric_maps(self):
        out = cc("template", "skirt", "--size", "512", project=self.p)
        mask = out["templates"]["skirt"]["mask"]
        cc("garment", "set", "skirt", "--fabric", "denim", "--height", mask, project=self.p)
        bad = cc("garment", "set", "skirt", "--fabric", "velvet", project=self.p, ok=False)
        self.assertEqual(bad["error"]["code"], "unknown_fabric")
        out = cc("build", project=self.p)
        mats = {m["name"]: m for m in glb_json(out["glb"])["materials"]}
        self.assertIn("normalTexture", mats["Garment_skirt"])
        self.assertIn("normalTexture", mats["Garment_tanktop"])  # default fabric preset


def glb_json(path):
    with open(path, "rb") as f:
        data = f.read()
    n = int.from_bytes(data[12:16], "little")
    return json.loads(data[20:20 + n])


class AutoRig(unittest.TestCase):
    def test_autorig_reference_body(self):
        tmp = tempfile.mkdtemp()
        ref = os.path.join(tmp, "ref.glb")
        cc("reference-body", "--out", ref)
        out = cc("autorig", ref, "--out", os.path.join(tmp, "rigged.glb"))
        self.assertIn(out["skinning"]["method"], ("heat", "heat_proxy", "proximity"))
        v = cc("validate", out["glb"])
        self.assertTrue(v["valid"], v["checks"])

    def test_autorig_awkward_input(self):
        """A-pose, facing +X, centimetres, shape key, output folder that doesn't exist yet."""
        tmp = tempfile.mkdtemp()
        ref = os.path.join(tmp, "ref.glb")
        cc("reference-body", "--out", ref, "--with-rig")
        src = os.path.join(tmp, "variant.glb")
        subprocess.run([sys.executable, os.path.join(ROOT, "tests", "make_autorig_variant.py"), ref, src],
                       check=True, capture_output=True)
        out = cc("autorig", src, "--out", os.path.join(tmp, "new", "dir", "rigged.glb"), "--animations", "Walk")
        self.assertEqual(out["facing_detected"], "+x")
        self.assertEqual(out["scaled_by"], 0.01)
        self.assertIn("joints", out)
        with open(src[:-4] + ".joints.json") as f:
            truth = json.load(f)
        H = out["height_m"]
        for bone, p in truth.items():
            got = out["joints"][bone]
            err = sum((a - b) ** 2 for a, b in zip(got, p)) ** 0.5 * out["scaled_by"]
            self.assertLess(err / H, 0.06, f"{bone}: {got} vs {p}")
        v = cc("validate", out["glb"])
        self.assertTrue(v["valid"], v["checks"])
        self.assertTrue(any(m.get("extras", {}).get("targetNames") for m in glb_json(out["glb"])["meshes"]),
                        "shape key lost")


if __name__ == "__main__":
    unittest.main()
