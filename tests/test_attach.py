"""Accessories (#7), props (#9) and extra bone chains (#10). Run: python -m unittest tests.test_attach"""
import os
import tempfile
import unittest

import numpy as np

from test_cli import cc

try:
    import bpy  # noqa: F401  (loads mathutils for the kankuro.blender modules)
except ImportError:  # pragma: no cover
    bpy = None


def _build(project):
    from kankuro import spec as specmod
    from kankuro.blender import build
    return build.build_scene(specmod.load(project), project, tempfile.mkdtemp())


def _project(preset, *sets):
    p = os.path.join(tempfile.mkdtemp(), "c")
    cc("init", p, "--preset", preset)
    cc("set", "face.blendshapes=none", "export.texture_size=512", *sets, project=p)
    return p


def _alive(b):
    try:
        b.arm.name
        return True
    except (ReferenceError, AttributeError):
        return False


def _signed(bvh, pts):
    from mathutils import Vector
    out = []
    for p in pts:
        loc, nrm, _, _ = bvh.find_nearest(Vector(p))
        out.append((Vector(p) - loc).dot(nrm))
    return np.array(out)


def _necklace(path):
    """A simple torus necklace modelled on the reference body, round the neck and down onto the chest."""
    import math
    from kankuro.blender import accessories, build, util
    ref = build.reference_body()
    nb = ref.arm.data.bones["neck_01"]
    c = np.array(nb.head_local) + np.array([0, -0.035, -0.06])
    v, f = accessories._torus(0.1, 0.004, c, (0, -math.sin(0.6), math.cos(0.6)), seg=64, rseg=8)
    obj = util.make_mesh("haar", v, f)
    util.select_only(obj)
    bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, export_materials=False)
    bpy.data.objects.remove(obj, do_unlink=True)
    return path


class Accessories(unittest.TestCase):
    """A crown on the head, bangles that hug the wrist, a necklace on the chest, on several bodies."""

    BODIES = [
        ("athletic_male", ()),
        ("elder_female", ()),
        ("child", ()),
        ("female", ("body.macros.weight=0.2", "body.macros.muscle=0.2", "body.macros.breast_size=0.0")),
        ("female", ("body.macros.weight=0.8", "body.macros.muscle=0.8", "body.macros.breast_size=1.0",
                    "body.height_cm=178")),
    ]

    @classmethod
    def setUpClass(cls):
        cls.necklace = _necklace(os.path.join(tempfile.mkdtemp(), "haar.obj"))

    def _dress(self, p):
        cc("accessory", "add", "circlet", project=p)
        cc("accessory", "add", "bangle_l", project=p)
        cc("accessory", "add", "haar", "--file", self.necklace, "--bone", "spine_03", "--fit", "chest",
           "--material", "gold", project=p)

    def test_cli_contract(self):
        p = _project("female")
        out = cc("accessory", "list", project=p)
        self.assertEqual(set(out["builtins"]), {"circlet", "ring_earring_l", "ring_earring_r", "bangle_l", "bangle_r"})
        a = cc("accessory", "add", "crown", "--builtin", "circlet", "--offset", "0,0,0.01", "--material", "silver",
               project=p)["accessory"]
        self.assertEqual((a["bone"], a["offset"], a["material"]), ("head", [0.0, 0.0, 0.01], "silver"))
        bad = cc("accessory", "add", "x", "--file", self.necklace, "--bone", "hed", project=p, ok=False)
        self.assertEqual(bad["error"]["code"], "unknown_bone")
        self.assertIn("spine_03", bad["error"]["hint"])
        bad = cc("accessory", "add", "y", "--file", self.necklace, project=p, ok=False)
        self.assertEqual(bad["error"]["code"], "missing_arg")
        self.assertEqual(cc("accessory", "add", "crown", project=p, ok=False)["error"]["code"], "duplicate_id")
        cc("accessory", "remove", "crown", project=p)
        self.assertEqual(cc("accessory", "list", project=p)["accessories"], [])
        cc("catalog", "presets")  # still fine

    def test_fits_on_every_body(self):
        from kankuro.blender import garments, util
        for preset, sets in self.BODIES:
            with self.subTest(body=preset, sets=sets):
                p = _project(preset, *sets)
                self._dress(p)
                b = _build(p)
                body = garments.body_bvh(b.body)
                acc = {m["accessory_id"]: util.get_coords(m) for m in b.meshes if m.get("accessory_id")}
                # the crown sits on the head, not in it, and touches it somewhere
                d = _signed(body, acc["circlet"])
                self.assertGreater(d.min(), 0.0005)
                self.assertLess(d.min(), 0.01)
                # the bangle hugs the wrist: no gap all round, no cutting in
                d = _signed(body, acc["bangle_l"])
                self.assertGreater(d.min(), 0.0)
                self.assertLess(d.min(), 0.004)
                # the necklace lies on the chest: nothing inside, the front of it on the skin
                d = _signed(body, acc["haar"])
                self.assertGreater(d.min(), 0.0)
                front = acc["haar"][:, 1] < np.percentile(acc["haar"][:, 1], 15)
                self.assertLess(np.median(d[front]), 0.008)

    def test_rigid_follows_one_bone_and_presses_the_hair(self):
        from kankuro.blender import build, util
        p = _project("female")
        cc("hair", "set", "short", project=p)
        self._dress(p)
        cc("accessory", "add", "ring_earring_l", project=p)
        b = _build(p)
        m = {o.get("accessory_id"): o for o in b.meshes if o.get("accessory_id")}
        W = util.weight_matrix(m["circlet"], ["head"])
        np.testing.assert_allclose(W[:, 0], 1.0)
        self.assertEqual({g.name for g in m["ring_earring_l"].vertex_groups}, {"ring_earring_l_01"})
        # hair at the band's height is under the band
        co = util.get_coords(m["circlet"])
        hb = b.arm.data.bones["head"]
        axis = np.array(hb.tail_local - hb.head_local)
        axis /= np.linalg.norm(axis)
        head = np.array(hb.head_local)

        def radial(pts):
            r = pts - head
            return r - np.outer(r @ axis, axis), r @ axis
        rc, hc = radial(co)
        hair = util.get_coords(b.hair)
        rh, hh = radial(hair)
        band = (hh > hc.min() + 0.002) & (hh < hc.max() - 0.002)
        ang_c = np.arctan2(rc[:, 1], rc[:, 0])
        ang_h = np.arctan2(rh[band, 1], rh[band, 0])
        near = [np.linalg.norm(rc[np.abs(((ang_c - a + np.pi) % (2 * np.pi)) - np.pi) < 0.1], axis=1) for a in ang_h]
        rin, rout = np.array([x.min() for x in near]), np.array([x.max() for x in near])
        r = np.linalg.norm(rh[band], axis=1)
        self.assertEqual((r > rout).sum(), 0)          # no hair shows through or over the band
        # at most 2 mm into its thickness, except where the band rests on the scalp itself (just above the
        # ear): there the hair is pressed flat, as close to the skin as squeeze_hair goes (1.5 mm)
        deep = (r - rin) >= 0.002
        if deep.any():
            from mathutils import Vector
            from kankuro.blender import garments
            bvh = garments.body_bvh(b.body)
            skin = np.array([bvh.find_nearest(Vector(q))[3] for q in hair[band][deep]])
            self.assertLess(skin.max(), 0.0016)
        # posed on Walk, the circlet keeps its shape exactly
        build.pose_clip(b, "Walk", 0.3)
        posed = util.get_coords(m["circlet"], evaluated=True)
        e = np.array([[ed.vertices[0], ed.vertices[1]] for ed in m["circlet"].data.edges])
        np.testing.assert_allclose(np.linalg.norm(posed[e[:, 0]] - posed[e[:, 1]], axis=1),
                                   np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1), atol=1e-5)

    def test_glb_meshes_and_validate(self):
        p = _project("female")
        self._dress(p)
        cc("accessory", "add", "ring_earring_r", project=p)
        out = cc("build", "--animations", "Idle_A", project=p)
        names = {m["name"] for m in out["meshes"]}
        self.assertTrue({"circlet", "bangle_l", "haar", "ring_earring_r"} <= names)
        v = cc("validate", out["glb"])
        self.assertTrue(v["valid"], v)
        chk = {c["check"]: c for c in v["checks"]}
        self.assertEqual(chk["bone_names"]["detail"]["missing"], [])
        self.assertEqual(chk["extra_bones"]["detail"]["by_parent"], {"head": ["ring_earring_r_01"]})


class Props(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _project("male")
        cc("prop", "add", "staff", project=cls.p)                      # right hand, 4 cm
        cc("prop", "add", "handle", "--hand", "l", project=cls.p)      # left hand, 3 cm
        cls._b = None

    @property
    def b(self):
        """The built scene (rebuilt when another test reset it)."""
        if not _alive(type(self)._b):
            type(self)._b = _build(self.p)
        return type(self)._b

    def _finger_depth(self, b, prop, side):
        """How deep the fingers of `side` go into `prop` (m, 0 = not at all), in the current pose."""
        from mathutils.bvhtree import BVHTree
        from mathutils import Vector
        from kankuro.blender import util
        # the thumb's base (thumb_01) is palm flesh, pressed against the grip like the palm
        fingers = [f"{n}_0{k}_{side}" for n in ("thumb", "index", "middle", "ring", "pinky") for k in (1, 2, 3)
                   if (n, k) != ("thumb", 1)]
        W = util.weight_matrix(b.body, fingers).sum(1)
        pts = util.get_coords(b.body, evaluated=True)[W > 0.5]
        o = next(m for m in b.meshes if m.get("prop_id") == prop)
        co = util.get_coords(o, evaluated=True)
        bvh = BVHTree.FromPolygons([Vector(c) for c in co], [list(f.vertices) for f in o.data.polygons])
        return max(0.0, -_signed(bvh, pts).min())

    def _in_hand(self, b, prop, side):
        from kankuro.blender import util
        o = next(m for m in b.meshes if m.get("prop_id") == prop)
        co = util.get_coords(o, evaluated=True)
        M = np.array(b.arm.matrix_world @ b.arm.pose.bones[f"hand_{side}"].matrix)
        return (np.linalg.inv(M) @ np.c_[co, np.ones(len(co))].T).T[:, :3]

    def test_grip_without_finger_penetration_through_walk(self):
        from kankuro.blender import build, props
        b = self.b
        props.pose_grips(b)
        rest = {k: self._in_hand(b, k, s) for k, s in (("staff", "r"), ("handle", "l"))}
        for k, s in (("staff", "r"), ("handle", "l")):
            self.assertLess(self._finger_depth(b, k, s), 0.003, k)
        for f in (0.0, 0.5, 1.0):
            build.pose_clip(b, "Walk", f)
            for k, s in (("staff", "r"), ("handle", "l")):
                self.assertLess(self._finger_depth(b, k, s), 0.003, (k, f))
                np.testing.assert_allclose(self._in_hand(b, k, s), rest[k], atol=2e-4)  # no drift

    def test_grip_closes_the_fingers(self):
        g = {x["id"]: x for x in self.b.grips}
        from mathutils import Quaternion
        angle = Quaternion(g["staff"]["pose"]["middle_02_r"]).angle
        self.assertGreater(np.degrees(angle), 20)

    def test_export_has_sockets_and_baked_grips(self):
        out = cc("build", "--animations", "Walk", project=self.p)
        v = cc("validate", out["glb"])
        self.assertTrue(v["valid"], v)
        chk = {c["check"]: c for c in v["checks"]}
        self.assertEqual(chk["extra_bones"]["detail"]["by_parent"], {"hand_l": ["prop_l"], "hand_r": ["prop_r"]})
        import bpy
        from kankuro.blender import util
        util.reset_scene()
        bpy.ops.import_scene.gltf(filepath=out["glb"])
        act = next(a for a in bpy.data.actions if a.name.startswith("Walk"))
        from kankuro.blender import motion
        q = motion.read_quats(act, "middle_02_r", [act.frame_range[0], act.frame_range[1]])
        self.assertGreater(np.degrees(2 * np.arccos(min(1.0, abs(q[0, 0])))), 20)  # curled on every frame

    def test_render_warns_when_the_prop_cuts_into_the_body(self):
        p = _project("male")
        cc("prop", "add", "handle", "--hand", "l", "--offset=-0.8,0,-0.1", project=p)
        r = cc("render", "--views", "front", "--size", "64", "--samples", "1", project=p)
        self.assertIn("prop_penetration", [w["code"] for w in r.get("warnings", [])])


class TwoHands(unittest.TestCase):
    def test_flute_second_hand_on_idle(self):
        from mathutils import Vector
        from kankuro.blender import build, motion
        p = _project("male")
        cc("prop", "add", "flute", project=p)
        b = _build(p)
        g = b.grips[0]
        self.assertEqual((g["anchor"], g["second"]), ("r", "l"))
        build.pose_clip(b, "Idle_A", 0.4)
        self.assertEqual([w for w in b.warnings if w["code"] == "second_hand_unreachable"], [])
        S = b.arm.pose.bones["prop_r"].matrix
        tgt = S @ Vector(g["target"])
        self.assertLess((b.arm.pose.bones["hand_l"].head - tgt).length, 0.01)


class ExtraBones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _project("male")
        cc("bones", "add", "tail", "--parent", "pelvis", "--count", "8", "--length", "0.9", "--curve", "up:0.3",
           "--taper", "0.5", "--radius", "0.035", project=cls.p)
        cls._b = None

    b = Props.b

    def test_cli(self):
        out = cc("bones", "list", project=self.p)
        self.assertEqual(out["extra_bones"][0]["bones"][-1], "tail_08")
        p = _project("male")
        bad = cc("bones", "add", "x", "--parent", "pelvs", project=p, ok=False)
        self.assertEqual(bad["error"]["code"], "unknown_bone")
        cc("bones", "add", "braid", "--parent", "head", "--count", "4", "--follow", "hair", project=p)
        cc("bones", "remove", "braid", project=p)
        self.assertEqual(cc("bones", "list", project=p)["extra_bones"], [])

    def test_no_extra_bones_keeps_the_skeleton(self):
        from kankuro.blender import rig
        b = _build(_project("male"))
        self.assertEqual(sorted(x.name for x in b.arm.data.bones), sorted(rig.m2m_bone_names()))

    def _sim(self, clip):
        from kankuro.blender import anim, motion
        b = self.b
        anim.pose_at(b.arm, clip, 0)
        act = b.arm.animation_data.action.copy()
        motion.prepare(b, act)
        f0, f1 = act.frame_range
        frames = np.arange(int(f0), int(f1) + 1)
        return {n: motion.read_quats(act, n, frames) for n in b.chains[0]["bones"]}, act

    def test_deterministic_and_loops(self):
        a, _ = self._sim("Walk")
        b, _ = self._sim("Walk")
        for n in a:
            np.testing.assert_array_equal(a[n], b[n])
        # seamless: the last frame matches the first on every bone, and the chain does move during the clip
        def deg(q0, q1):
            return 2 * np.degrees(np.arccos(min(1.0, abs(float(q0 @ q1)))))
        for n, q in a.items():
            self.assertLess(deg(q[0], q[-1]), 3.0, n)
        self.assertGreater(max(deg(q[0], x) for q in a.values() for x in q), 2.0)
        jog, _ = self._sim("Jog")       # a livelier clip swings it further
        self.assertGreater(max(deg(q[0], x) for q in jog.values() for x in q), 10.0)

    def test_tail_stays_out_of_the_legs(self):
        from kankuro.blender import build, motion, util
        b = self.b
        tail = next(m for m in b.meshes if m.get("extra_chain") == "tail")
        for clip in ("Walk", "Jog"):
            for f in (0.0, 0.25, 0.5, 0.75):
                build.pose_clip(b, clip, f)
                co = util.get_coords(tail, evaluated=True)
                for leg in motion.LEGS:
                    pb = b.arm.pose.bones[leg]
                    a, e = np.array(pb.head), np.array(pb.tail)
                    ab = e - a
                    t = np.clip((co - a) @ ab / (ab @ ab), 0, 1)
                    d = np.linalg.norm(co - (a + t[:, None] * ab), axis=1)
                    self.assertGreater(d.min(), b.capsules[leg] * 0.8, (clip, f, leg))

    def test_export_validates(self):
        out = cc("build", "--animations", "Idle_A,Walk", project=self.p)
        v = cc("validate", out["glb"])
        self.assertTrue(v["valid"], v)
        chk = {c["check"]: c for c in v["checks"]}
        self.assertEqual(chk["extra_bones"]["detail"]["by_parent"]["pelvis"][0], "tail_01")
        self.assertEqual(chk["rest_orientation_matches_m2m"]["pass"], True)

    def test_braid_follows_the_hair(self):
        from kankuro.blender import util
        p = _project("female")
        cc("hair", "set", "indian_braid", project=p)
        cc("bones", "add", "braid", "--parent", "head", "--count", "5", "--follow", "hair", project=p)
        b = _build(p)
        names = [f"braid_0{k}" for k in range(1, 6)]
        W = util.weight_matrix(b.hair, names)
        self.assertGreater((W.sum(1) > 0.5).sum(), 100)
        self.assertGreater(W[:, -1].max(), 0.5)


class AutorigExtras(unittest.TestCase):
    def test_autorig_with_tail_and_staff(self):
        import math
        d = tempfile.mkdtemp()
        ref = os.path.join(d, "ref.glb")
        cc("reference-body", "--out", ref)
        src = os.path.join(d, "tailed.glb")
        import bpy
        from kankuro.blender import util
        util.reset_scene()
        bpy.ops.import_scene.gltf(filepath=ref)
        for o in list(bpy.data.objects):
            if o.type == "ARMATURE":
                bpy.data.objects.remove(o)
        cu = bpy.data.curves.new("t", "CURVE")
        cu.dimensions = "3D"
        sp = cu.splines.new("BEZIER")
        sp.bezier_points.add(2)
        for bp, c in zip(sp.bezier_points, [(0, 0.08, 0.95), (0, 0.45, 0.7), (0, 0.85, 0.9)]):
            bp.co = c
            bp.handle_left_type = bp.handle_right_type = "AUTO"
        cu.bevel_depth = 0.03
        o = bpy.data.objects.new("Tail", cu)
        bpy.context.collection.objects.link(o)
        util.select_only(o)
        bpy.ops.object.convert(target="MESH")
        for x in bpy.data.objects:
            x.select_set(True)
        bpy.ops.export_scene.gltf(filepath=src, export_format="GLB", use_selection=True)
        out = os.path.join(d, "out.glb")
        r = cc("autorig", src, "--out", out, "--extra-chain", "tail:Tail:6", "--prop", "staff", "--animations", "Walk")
        self.assertEqual(sorted(r["extra_bones"]), ["prop_r"] + [f"tail_0{k}" for k in range(1, 7)])
        v = cc("validate", out)
        self.assertTrue(v["valid"], v)
        bad = cc("autorig", src, "--out", out, "--extra-chain", "tail:Nope", ok=False)
        self.assertEqual(bad["error"]["code"], "unknown_part")
        self.assertTrue(math.isfinite(r["seconds"]))


if __name__ == "__main__":
    unittest.main()
