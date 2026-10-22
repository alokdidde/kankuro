"""Facial blendshapes (ARKit 52). Run: python -m unittest tests.test_face"""
import os
import tempfile
import unittest

import numpy as np

from test_cli import cc


class FaceDeltas(unittest.TestCase):
    def test_all_52_move_the_face(self):
        from kankuro import face, morph
        co = morph.morphed_coords()
        self.assertEqual(len(face.ARKIT_NAMES), 52)
        d = face.deltas(co, face.ARKIT_NAMES)
        for n, v in d.items():
            self.assertGreater(np.linalg.norm(v, axis=1).max(), 0.002, n)
        # left/right are the character's own (+X in Blender is its left)
        self.assertLess(np.abs(d["mouthSmileLeft"][co[:, 0] < -0.02]).max(), 1e-6)
        self.assertGreater(np.abs(d["eyeBlinkLeft"][co[:, 0] > 0]).max(), 0.005)

    def test_parse_expression(self):
        from kankuro import face
        w, bad = face.parse_expression("smile,jawOpen=0.3")
        self.assertIsNone(bad)
        self.assertEqual(w["jawOpen"], 0.3)
        self.assertEqual(w["mouthSmileLeft"], 1.0)
        self.assertEqual(face.parse_expression("grin")[1], "grin")


class FaceBuild(unittest.TestCase):
    def test_build_has_blendshapes_and_validates(self):
        p = os.path.join(tempfile.mkdtemp(), "face")
        cc("init", p, "--preset", "female")
        out = cc("build", project=p)
        self.assertEqual(out["blendshapes"]["count"], 52)
        v = cc("validate", out["glb"])
        self.assertTrue(v["valid"], v)
        check = next(c for c in v["checks"] if c["check"] == "arkit_blendshapes")
        self.assertEqual(check["detail"]["missing"], [])
        r = cc("render", "--views", "front", "--focus", "head", "--size", "128", "--samples", "2",
               "--expression", "surprise", project=p)
        self.assertIn("browInnerUp", r["expression"])
        bad = cc("render", "--expression", "jawOpn=1", project=p, ok=False)
        self.assertEqual(bad["error"]["code"], "bad_expression")
        cc("set", "face.blendshapes=none", project=p)
        out = cc("build", project=p)
        self.assertEqual(out["blendshapes"]["count"], 0)


class SkinDetail(unittest.TestCase):
    """#6: faces at darker tones need tone variation, readable eyes and tone-aware shading."""

    def test_detail_varies_the_face_tone(self):
        from PIL import Image
        from kankuro import textures
        d = tempfile.mkdtemp()
        flat = textures.skin_texture("#7f4f32", os.path.join(d, "flat.png"), size=512, detail=False)
        rich = textures.skin_texture("#7f4f32", os.path.join(d, "rich.png"), size=512, detail=True)
        a = np.asarray(Image.open(flat)).astype(float)
        b = np.asarray(Image.open(rich)).astype(float)
        # warmer cheeks/nose, darker lids: the tone spreads out (it was nearly one flat value)
        self.assertGreater(b[..., 0].std(), a[..., 0].std() * 1.2)
        self.assertGreater((np.abs(b - a).max(-1) > 25).sum(), 200)  # lash lines, lids
        reg = textures.face_regions()
        for k in ("cheeks", "nose", "lids", "lash", "under", "tzone"):
            self.assertGreater(reg[k].max(), 0.5, k)

    def test_roughness_map_has_a_shinier_tzone(self):
        from PIL import Image
        from kankuro import textures
        out = textures.skin_roughness(0.6, os.path.join(tempfile.mkdtemp(), "r.png"), size=256)
        g = np.asarray(Image.open(out))[..., 1] / 255
        self.assertLess(g.min(), 0.5)
        self.assertAlmostEqual(float(np.median(g)), 0.64, delta=0.02)

    def test_shading_depends_on_tone(self):
        import bpy  # noqa: F401
        from kankuro.blender import materials
        fair, dark = materials.skin_shading("#f1c7a8", 0.6), materials.skin_shading("#7f4f32", 0.6)
        self.assertLess(dark["subsurface"], fair["subsurface"])
        self.assertGreater(dark["specular"], fair["specular"])

    def test_sclera_is_bright(self):
        import bpy  # noqa: F401
        from PIL import Image
        from kankuro.blender import materials, rig
        src = os.path.join(rig.DATA, "eyes", "brown_eye.png")
        out = materials.eye_texture(src, os.path.join(tempfile.mkdtemp(), "e.png"), "#3b2416")
        a = np.asarray(Image.open(src).convert("RGB")).astype(float)
        b = np.asarray(Image.open(out).convert("RGB")).astype(float)
        white = (a.max(-1) - a.min(-1)) / (a.max(-1) + 1e-6) < 0.25
        white &= a.mean(-1) > 0.6 * 255
        self.assertGreater(b[white].mean(), a[white].mean())


if __name__ == "__main__":
    unittest.main()
