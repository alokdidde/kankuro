"""Material presets (#8): metals, gems, pearl, lacquer, zari borders. Run: python -m unittest tests.test_materials"""
import json
import os
import struct
import tempfile
import unittest

import numpy as np

from test_cli import cc

try:
    import bpy  # noqa: F401  (loads mathutils for the kankuro.blender modules)
except ImportError:  # pragma: no cover
    bpy = None


def _glb_json(path):
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


class Presets(unittest.TestCase):
    def test_catalog_lists_presets_with_values(self):
        out = cc("catalog", "materials")["materials"]
        want = {"gold", "rose_gold", "brass", "bronze", "silver", "steel", "iron_dark", "gem", "pearl",
                "gold_zari", "lacquer"}
        self.assertEqual(set(out["presets"]), want)
        for name, p in out["presets"].items():
            for k in ("color", "metallic", "roughness", "kind", "desc"):
                self.assertIn(k, p, name)
        self.assertEqual(out["presets"]["gem"]["transmission"], 1.0)
        self.assertEqual(set(out["regions"]) & {"border", "hem"}, {"border", "hem"})

    def test_resolve_overrides(self):
        from kankuro import matlib
        self.assertEqual(matlib.resolve("gem", color="#1f5fbf")["color"], "#1f5fbf")
        r = matlib.resolve({"preset": "gold", "roughness": 0.5})
        self.assertEqual((r["roughness"], r["metallic"]), (0.5, 1.0))
        self.assertEqual(matlib.resolve("gold", roughness=0.1)["roughness"], 0.1)

    def test_garment_cli_and_spec_checks(self):
        p = os.path.join(tempfile.mkdtemp(), "m")
        cc("init", p, "--preset", "female")
        cc("garment", "add", "tshirt", "--color", "#335577", project=p)
        g = cc("garment", "set", "tshirt", "--material", "gold", project=p)["garment"]
        self.assertEqual(g["material"], "gold")
        self.assertNotIn("color", g)  # the preset's own colour shows
        g = cc("garment", "set", "tshirt", "--material", "gem", "--color", "#1f5fbf", project=p)["garment"]
        self.assertEqual((g["material"], g["color"]), ("gem", "#1f5fbf"))
        g = cc("garment", "set", "tshirt", "--material", "none", "--material-region", "border=gold_zari",
               "--material-region", "hem=gem:#1f5fbf", project=p)["garment"]
        self.assertNotIn("material", g)
        self.assertEqual(g["material_regions"], {"border": "gold_zari", "hem": {"preset": "gem", "color": "#1f5fbf"}})
        g = cc("garment", "set", "tshirt", "--material-region", "border=none", project=p)["garment"]
        self.assertEqual(list(g["material_regions"]), ["hem"])
        bad = cc("garment", "set", "tshirt", "--material", "unobtainium", project=p, ok=False)
        self.assertEqual(bad["error"]["code"], "unknown_material")
        self.assertIn("gold", bad["error"]["hint"])
        bad = cc("garment", "set", "tshirt", "--material-region", "trim=silver", project=p, ok=False)
        self.assertEqual(bad["error"]["code"], "missing_arg")  # a custom region needs --mask
        from PIL import Image
        mask = os.path.join(tempfile.mkdtemp(), "trim.png")
        Image.new("L", (64, 64), 255).save(mask)
        g = cc("garment", "set", "tshirt", "--material-region", "trim=silver", "--mask", mask, project=p)["garment"]
        self.assertTrue(g["material_regions"]["trim"]["mask"].startswith("assets/textures/"))
        # a hand-edited spec is checked too
        from kankuro import spec as specmod
        from kankuro.errors import CliError
        s = specmod.load(p)
        s["garments"][0]["material"] = "steal"
        with self.assertRaises(CliError) as e:
            specmod.validate(s, p)
        self.assertEqual(e.exception.code, "unknown_material")


class RegionBake(unittest.TestCase):
    """The fabric bake with a region: tinted, metallic in the mr map, same relief (pure numpy)."""

    def test_zari_keeps_the_weave_and_tints_only_the_region(self):
        from PIL import Image
        from kankuro import fabric, matlib
        d = tempfile.mkdtemp()
        size = 256
        mask = np.zeros((size, size), bool)
        mask[20:236, 20:236] = True
        region = np.zeros((size, size), np.float32)
        region[200:236, 20:236] = 1.0
        kw = dict(mask=mask, color="#7d1a2c", fabric="silk")
        a0, n0, m0 = fabric.bake(os.path.join(d, "plain"), size, 0.45, **kw)
        a1, n1, m1 = fabric.bake(os.path.join(d, "zari"), size, 0.45, regions=[(region, matlib.resolve("gold_zari"))], **kw)
        self.assertIsNone(m0["mr"])
        np.testing.assert_array_equal(np.asarray(Image.open(n0)), np.asarray(Image.open(n1)))
        A0, A1 = (np.asarray(Image.open(x)).astype(float) for x in (a0, a1))
        self.assertLess(np.abs(A1[50:150] - A0[50:150]).max(), 3)  # outside: unchanged (JPEG noise)
        gold = A1[210:230, 40:200].reshape(-1, 3).mean(0)
        self.assertGreater(gold[1], 140)  # yellow, not the red cloth
        self.assertGreater(gold[0], gold[2] + 40)
        mr = np.asarray(Image.open(m1["mr"])).astype(float) / 255
        self.assertGreater(mr[210:230, 40:200, 2].mean(), 0.8)  # metallic (B)
        self.assertLess(mr[50:150, 50:150, 2].max(), 0.01)
        self.assertAlmostEqual(mr[50:150, 50:150, 1].mean(), fabric.FABRICS["silk"]["rough"], delta=0.01)


class MaterialBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = os.path.join(tempfile.mkdtemp(), "m")
        cc("init", cls.p, "--preset", "male")
        cc("set", "export.texture_size=512", project=cls.p)
        cc("garment", "add", "tshirt", "--material", "gem", "--color", "#1f5fbf", project=cls.p)
        cc("garment", "add", "dhoti", "--material-region", "border=gold_zari", project=cls.p)
        cls.out = cc("build", project=cls.p)

    def test_glb_uses_pbr_and_gem_extensions(self):
        j = _glb_json(self.out["glb"])
        mats = {m["name"]: m for m in j["materials"]}
        gem = mats["Garment_tshirt"]
        self.assertIn("KHR_materials_transmission", gem["extensions"])
        self.assertAlmostEqual(gem["extensions"]["KHR_materials_ior"]["ior"], 1.76, places=2)
        self.assertEqual(gem["pbrMetallicRoughness"].get("metallicFactor"), 0)
        dhoti = mats["Garment_dhoti"]["pbrMetallicRoughness"]
        self.assertIn("metallicRoughnessTexture", dhoti)  # zari border: metallic only where it is
        self.assertIn("normalTexture", mats["Garment_dhoti"])
        v = cc("validate", self.out["glb"])
        self.assertTrue(v["valid"], v)

    def test_border_mask_follows_the_open_edges(self):
        from PIL import Image
        mr = np.asarray(Image.open(os.path.join(self.p, "build", "work", "garment_dhoti_mr.png")))
        metal = mr[..., 2] > 127
        self.assertTrue(0.02 < metal.mean() < 0.4, metal.mean())

    def test_template_writes_region_masks(self):
        from PIL import Image
        t = cc("template", "dhoti", "--size", "512", project=self.p)["templates"]["dhoti"]
        b = np.asarray(Image.open(t["border_mask"])) > 127
        h = np.asarray(Image.open(t["hem_mask"])) > 127
        m = np.asarray(Image.open(t["mask"]).convert("L")) > 127
        self.assertGreater(b.sum(), h.sum())
        self.assertGreater(h.sum(), 0)
        self.assertLess((b & ~m).sum(), 0.02 * b.sum())  # inside the garment


class EdgeDistance(unittest.TestCase):
    def test_saree_border_skips_the_tucked_waist(self):
        from test_garments import _build, _saree_woman
        from kankuro.blender import drape, garments, util
        b = _build(_saree_woman(tempfile.mkdtemp()))
        saree = next(m for m in b.meshes if m.get("garment_id") == "saree")
        d = garments.edge_distance(saree, "border", cap=0.2, uv_scale=b.uv_info["saree"]["scale_px_per_m"])
        co = util.get_coords(saree)
        n_skirt = len(co) // 2 - drape.ROWS * drape.COLS  # outer shell: skirt verts, then the pallu
        skirt = co[:n_skirt]
        self.assertLess(d[:n_skirt][skirt[:, 2] < skirt[:, 2].min() + 0.003].max(), 1e-6)  # hem
        self.assertGreater(d[:n_skirt][skirt[:, 2] > skirt[:, 2].max() - 0.003].min(), 0.05)  # waistband
        hem = garments.edge_distance(saree, "hem", cap=0.2)
        self.assertGreater(hem[n_skirt:n_skirt + drape.COLS].min(), 0.0)


if __name__ == "__main__":
    unittest.main()
