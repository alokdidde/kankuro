"""#14: the toes bend at the ball of the foot. Run: python -m unittest tests.test_feet"""
import os
import tempfile
import unittest

import numpy as np

from test_cli import cc

try:
    import bpy  # noqa: F401  (loads mathutils for the kankuro.blender modules)
except ImportError:  # pragma: no cover
    bpy = None


def _build(*sets, preset="male"):
    from kankuro import spec as specmod
    from kankuro.blender import build
    p = os.path.join(tempfile.mkdtemp(), "c")
    cc("init", p, "--preset", preset)
    cc("set", "face.blendshapes=none", *sets, project=p)
    return build.build_scene(specmod.load(p), p, tempfile.mkdtemp()), p


def _areas(co, F):
    a, b, c = co[F[:, 0]], co[F[:, 1]], co[F[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


class BallOfTheFoot(unittest.TestCase):
    BODIES = [("male", ()), ("female", ()), ("child", ()), ("male", ("body.height_cm=195",)),
              ("female", ("body.height_cm=150", "body.macros.weight=0.9"))]

    def test_pivot_on_the_crease_with_a_soft_blend(self):
        from kankuro.blender import util, validate
        for preset, sets in self.BODIES:
            with self.subTest(body=preset, sets=sets):
                b, _ = _build(*sets, preset=preset)
                crease = validate._ball_at_crease(b.arm, [b.body])
                self.assertEqual(set(crease), {"l", "r"})
                for side, d in crease.items():
                    self.assertLess(abs(d), 0.01, (side, d))
                # foot -> ball share blends over the crease: none 3 cm behind it, all 3 cm ahead
                bone = b.arm.data.bones["ball_l"]
                head = np.array(bone.head_local)
                fwd = np.array(bone.tail_local - bone.head_local)
                fwd[2] = 0
                fwd /= np.linalg.norm(fwd)
                W = util.weight_matrix(b.body, ["foot_l", "ball_l"])
                foot = W.sum(1) > 0.5
                d = (util.get_coords(b.body)[foot] - head) @ fwd
                f = W[foot, 1] / W[foot].sum(1)
                self.assertLess(f[d < -0.03].max(), 0.05)
                self.assertGreater(f[d > 0.03].min(), 0.95)
                mid = (f > 0.1) & (f < 0.9)
                foot_len = d.max() - (util.get_coords(b.body)[foot] @ fwd).min() + head @ fwd
                self.assertGreater(np.ptp(d[mid]), 0.12 * foot_len)  # not a 2 cm step (MakeHuman's)

    def test_toe_off_keeps_the_skin(self):
        """At Walk's toe-off (ball_l 25 degrees) the crease bends without pinching."""
        from kankuro.blender import build, util
        b, _ = _build()
        b.body.data.calc_loop_triangles()
        F = np.array([t.vertices[:] for t in b.body.data.loop_triangles])
        W = util.weight_matrix(b.body, ["foot_l", "ball_l"])
        f = W[:, 1] / np.maximum(W.sum(1), 1e-9)
        band = ((W.sum(1) > 0.5) & (f > 0.02) & (f < 0.98))[F].all(1)
        a0 = _areas(util.get_coords(b.body), F[band])
        build.pose_clip(b, "Walk", 0.5)
        self.assertGreater(np.degrees(b.arm.pose.bones["ball_l"].matrix_basis.to_quaternion().angle), 20)
        a1 = _areas(util.get_coords(b.body, evaluated=True), F[band])
        self.assertGreater((a1 / a0).min(), 0.6)   # was 0.34: the toes folded into a pinch

    def test_foot_shape_unchanged(self):
        """Moving the pivot must not tip the foot: the sole stays on the ground, toes level."""
        from kankuro.blender import util
        b, _ = _build()
        co = util.get_coords(b.body)
        W = util.weight_matrix(b.body, ["ball_l"])[:, 0]
        toes = co[W > 0.9]
        self.assertLess(toes[:, 2].min(), 0.01)
        self.assertGreater(toes[:, 2].max(), 0.025)

    def test_validate_and_autorig(self):
        d = tempfile.mkdtemp()
        b, p = _build()
        out = cc("build", project=p)
        v = cc("validate", out["glb"])
        chk = {c["check"]: c for c in v["checks"]}
        self.assertTrue(chk["ball_at_toe_crease"]["pass"], chk["ball_at_toe_crease"])
        ref = os.path.join(d, "ref.glb")
        cc("reference-body", "--out", ref)
        rig = os.path.join(d, "rigged.glb")
        cc("autorig", ref, "--out", rig)
        v = cc("validate", rig)
        chk = {c["check"]: c for c in v["checks"]}
        self.assertTrue(v["valid"], v)
        self.assertLess(max(abs(x) for x in chk["ball_at_toe_crease"]["detail"]["cm_from_crease"].values()), 1.5)


if __name__ == "__main__":
    unittest.main()
