"""Facial blendshapes (ARKit 52). Run: python -m unittest tests.test_face"""
import os
import tempfile
import unittest

import numpy as np

from test_cli import cc


class FaceDeltas(unittest.TestCase):
    def test_all_52_move_the_face(self):
        from ccreator import face, morph
        co = morph.morphed_coords()
        self.assertEqual(len(face.ARKIT_NAMES), 52)
        d = face.deltas(co, face.ARKIT_NAMES)
        for n, v in d.items():
            self.assertGreater(np.linalg.norm(v, axis=1).max(), 0.002, n)
        # left/right are the character's own (+X in Blender is its left)
        self.assertLess(np.abs(d["mouthSmileLeft"][co[:, 0] < -0.02]).max(), 1e-6)
        self.assertGreater(np.abs(d["eyeBlinkLeft"][co[:, 0] > 0]).max(), 0.005)

    def test_parse_expression(self):
        from ccreator import face
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


if __name__ == "__main__":
    unittest.main()
