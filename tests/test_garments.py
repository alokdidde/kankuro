"""Garment geometry checks (saree pallu, skirts in motion, kurta over dhoti, ...), built in-process.
Run: python -m unittest tests.test_garments"""
import os
import tempfile
import unittest

import numpy as np

from test_cli import cc

try:
    import bpy  # noqa: F401  (loads mathutils for the sasori.blender modules)
except ImportError:  # pragma: no cover
    bpy = None


def _build(project):
    """Build a project's character in this process; returns the Built scene."""
    from sasori import spec as specmod
    from sasori.blender import build
    spec = specmod.load(project)
    return build.build_scene(spec, project, tempfile.mkdtemp())


def _saree_woman(tmp, fabric="cotton"):
    p = os.path.join(tmp, "woman")
    cc("init", p, "--preset", "female")
    cc("set", "body.macros.age=0.55", "body.macros.weight=0.5", "body.height_cm=158", project=p)
    cc("garment", "add", "blouse", "--color", "#5a2a1e", "--fabric", fabric, project=p)
    cc("garment", "add", "saree", "--color", "#a8432a", "--fabric", fabric, project=p)
    return p


class Saree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sasori.blender import drape, util
        cls.tmp = tempfile.mkdtemp()
        p = _saree_woman(cls.tmp)
        cc("set", "export.hide_body_under_clothes=false", project=p)  # measure against the whole skin
        orig = drape.pallu
        cap = {}

        def capture(*a, **k):
            o = orig(*a, **k)
            cap["co"] = util.get_coords(o).reshape(drape.ROWS, drape.COLS, 3).copy()
            return o
        drape.pallu = capture
        try:
            cls.b = _build(p)
        finally:
            drape.pallu = orig
        cls.P = cap["co"]

    def _surfaces(self):
        from sasori.blender import garments
        blouse = next(m for m in self.b.meshes if m.get("garment_id") == "blouse")
        return garments.body_bvh(self.b.body), garments.mesh_bvh([blouse])

    def test_pallu_has_no_holes(self):
        """#2: the pallu stays outside the skin and the blouse everywhere (nothing shows through)."""
        from mathutils import Vector
        body, blouse = self._surfaces()
        inside = 0
        for p in self.P.reshape(-1, 3):
            loc, nrm, _, _ = body.find_nearest(Vector(p))
            h = (Vector(p) - loc).dot(nrm)
            hit = blouse.ray_cast(loc + nrm * 0.0005, nrm, 0.04)
            need = hit[3] if hit[0] is not None else 0.0
            inside += h < need + 0.002
        self.assertEqual(inside, 0)

    def test_pallu_is_smooth(self):
        """#2/#3: no spikes or folds in the cloth (the old pallu creased into the underbust)."""
        P = self.P
        lap = 0.25 * (P[:-2, 1:-1] + P[2:, 1:-1] + P[1:-1, :-2] + P[1:-1, 2:]) - P[1:-1, 1:-1]
        self.assertLess(np.linalg.norm(lap, axis=2).max(), 0.012)

    def test_pallu_lies_on_the_back(self):
        """#3: down the back the pallu touches the back and seat instead of standing off as a board,
        and its hanging end is a level hem."""
        from sasori.blender import drape
        from mathutils import Vector
        body, _ = self._surfaces()
        bones = self.b.arm.data.bones
        z_top, z_seat = bones["spine_03"].head_local.z, bones["thigh_l"].head_local.z
        mid = self.P[:, drape.COLS // 2]
        back = (mid[:, 1] > 0.02) & (mid[:, 2] < z_top) & (mid[:, 2] > z_seat)
        self.assertGreater(back.sum(), 10)
        gaps = [(Vector(p) - body.find_nearest(Vector(p))[0]).length for p in mid[back]]
        self.assertLess(max(gaps), 0.045, gaps)
        self.assertLess(np.ptp(self.P[-1, :, 2]), 0.01)


class SkirtInMotion(unittest.TestCase):
    def test_skirt_follows_both_thighs_not_the_knees(self):
        """Skirts hang as one tube: the centre front is shared by both thighs, and no calf/foot
        weights on the front (the knee mustn't fold the cloth like a trouser leg)."""
        from sasori.blender import util
        b = _build(_saree_woman(tempfile.mkdtemp(), fabric="none"))
        saree = next(m for m in b.meshes if m.get("garment_id") == "saree")
        W = util.weight_matrix(saree, b.res.bones)
        co = util.get_coords(saree)
        bn = b.res.bones
        z_crotch = b.arm.data.bones["thigh_l"].head_local.z - 0.15
        front_mid = (np.abs(co[:, 0]) < 0.004) & (co[:, 1] < -0.05) & (co[:, 2] < z_crotch)
        self.assertGreater(front_mid.sum(), 3)
        wl, wr = W[front_mid, bn.index("thigh_l")], W[front_mid, bn.index("thigh_r")]
        self.assertGreater(wl.min(), 0.1)
        np.testing.assert_allclose(wl / (wl + wr), 0.5, atol=0.1)
        front = co[:, 1] < b.arm.data.bones["calf_l"].head_local.y - 0.03
        for leg in ("calf_l", "calf_r", "foot_l", "foot_r"):
            self.assertLess(W[front, bn.index(leg)].max(), 1e-6, leg)


def _uv_area_ratios(obj, scale):
    """Per-face UV area / (3D area x scale^2) over a garment's outer shell (1 = no squash)."""
    from sasori.blender import util
    me = obj.data
    co = util.get_coords(obj)
    uv = me.uv_layers["UVMap"].data
    n = obj.get("shell_faces", len(me.polygons))
    out = []
    for p in me.polygons[:n]:
        li = list(p.loop_indices)
        P = co[[me.loops[k].vertex_index for k in li]]
        U = np.array([uv[k].uv for k in li])
        a3 = sum(0.5 * np.linalg.norm(np.cross(P[k] - P[0], P[k + 1] - P[0])) for k in range(1, len(li) - 1))
        a2 = sum(0.5 * abs((U[k] - U[0])[0] * (U[k + 1] - U[0])[1] - (U[k] - U[0])[1] * (U[k + 1] - U[0])[0])
                 for k in range(1, len(li) - 1))
        out.append(a2 / max(a3 * scale * scale, 1e-12))
    return np.array(out)


class TraditionalDress(unittest.TestCase):
    """#4 dhoti and #5 kurta, built the way the issue's farmer was (kurta added first)."""

    @classmethod
    def setUpClass(cls):
        p = os.path.join(tempfile.mkdtemp(), "farmer")
        cc("init", p, "--preset", "male")
        cc("garment", "add", "kurta", "--color", "#e8e0cf", "--fabric", "cotton", project=p)
        cc("garment", "add", "dhoti", "--color", "#f1ece0", "--fabric", "cotton", project=p)
        cls.b = _build(p)
        cls.g = {m.get("garment_id"): m for m in cls.b.meshes if m.get("garment_id")}

    def test_cotton_is_woven_and_tshirts_are_jersey(self):
        from sasori import catalog, fabric
        self.assertEqual(fabric.FABRICS["cotton"]["kind"], "plain")
        self.assertEqual(fabric.FABRICS["jersey"]["kind"], "jersey")
        self.assertEqual(catalog.GARMENTS["tshirt"]["fabric"], "jersey")
        self.assertEqual(catalog.GARMENTS["dhoti"]["fabric"], "cotton")

    def test_uvs_are_not_squashed(self):
        """The fuzzy/ribbed patches came from faces squeezed to slivers in the UV layout."""
        from sasori.blender import dhoti
        for gid in ("dhoti", "kurta"):
            r = _uv_area_ratios(self.g[gid], self.b.uv_info[gid]["scale_px_per_m"])
            if gid == "dhoti":  # the pleat panel (joined last) reuses the folded cloth's UVs
                r = r[:-(dhoti.ROWS - 1) * (dhoti.COLS - 1)]
            self.assertGreater(np.percentile(r, 2), 0.2, gid)

    def test_kurta_is_over_the_dhoti_and_knee_length(self):
        from sasori.blender import garments, util
        from mathutils import Vector
        bones = self.b.arm.data.bones
        z_hip, z_knee = bones["thigh_l"].head_local.z, bones["calf_l"].head_local.z
        kurta = util.get_coords(self.g["kurta"])
        self.assertLess(kurta[:, 2].min(), z_knee + 0.02)  # falls to about the knee
        kb = garments.mesh_bvh([self.g["kurta"]])
        d = util.get_coords(self.g["dhoti"])
        hem = kurta[:, 2].min()
        sel = d[(d[:, 2] > hem + 0.06) & (d[:, 2] < z_hip)]
        covered = 0
        for p in sel:  # look outwards (away from the body axis) from each dhoti point
            out = Vector((p[0], p[1] - bones["pelvis"].head_local.y, 0)).normalized()
            covered += kb.ray_cast(Vector(p) + out * 0.0005, out, 0.3)[0] is not None
        self.assertGreater(covered / len(sel), 0.97)

    def test_kurta_collar_and_placket(self):
        me = self.g["kurta"].data
        a = np.empty(len(me.vertices), dtype=np.int32)
        me.attributes["collar"].data.foreach_get("value", a)
        self.assertGreater(a.sum(), 20)
        pk = self.b.uv_info["kurta"]["placket"]
        self.assertTrue(0 < pk["u"] < 0.5 and 0 < pk["v"] < 1)  # front half of the template

    def test_dhoti_has_front_pleats(self):
        from sasori.blender import util
        d = util.get_coords(self.g["dhoti"])
        bones = self.b.arm.data.bones
        z_knee = bones["calf_l"].head_local.z
        # cloth in front of the gap between the knees (the pleated panel), not two separate legs
        front_gap = (np.abs(d[:, 0]) < 0.02) & (np.abs(d[:, 2] - z_knee) < 0.05) & (d[:, 1] < bones["calf_l"].head_local.y)
        self.assertGreater(front_gap.sum(), 4)


if __name__ == "__main__":
    unittest.main()
