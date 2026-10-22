"""Hair coverage: every style reaches the nape and the skin behind the ears, but stays off the ears and the
face. Run: python -m unittest tests.test_hair"""
import unittest

import numpy as np

try:
    import bpy  # noqa: F401  (loads mathutils for the sasori.blender modules)
except ImportError:  # pragma: no cover
    bpy = None


@unittest.skipIf(bpy is None, "needs bpy")
class HairCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sasori import spec as specmod
        from sasori.blender import body, hair, util
        util.reset_scene()
        sp = specmod.default_spec(preset="female")
        cls.res = body.build(sp["body"].get("macros"), {}, None, face_keys=())
        cls.body = body.make_group_object(cls.res, "body", "Body")
        co, _, _, z_ref, z_top, yc = hair._head_frame(cls.res, cls.body)
        cls.co = co
        cls.verts = np.asarray(cls.body["mh_verts"])
        cls.theta = np.degrees(np.abs(np.arctan2(co[:, 0], -(co[:, 1] - yc))))
        cls.zf = (co[:, 2] - z_ref) / (z_top - z_ref)  # 0 = skull base, 1 = crown
        # the outside of the head and neck (the body mesh also has the mouth and throat inside it)
        cls.outer = np.hypot(co[:, 0], co[:, 1] - yc) > 0.06
        cls.ear = np.zeros(len(co), dtype=bool)
        cls.ear[hair.ear_vertices(cls.body)] = True

    def _coverage(self, style):
        """Per body vertex: 1 where the hair's base layer is over the skin (ray along the skin normal)."""
        import bpy as _bpy
        from sasori.blender import hair
        h = hair.make(self.res, self.body, style)
        try:
            return hair.coverage_mask(self.res, h, smooth=0)[self.verts]
        finally:
            _bpy.data.objects.remove(h, do_unlink=True)

    def _regions(self):
        th, zf, ear, out = self.theta, self.zf, self.ear, self.outer
        return {
            "nape": (th > 155) & (zf > -0.22) & (zf < 0.3) & out,
            "behind_ear": (th > 125) & (th < 150) & (zf > -0.05) & (zf < 0.45) & ~ear & out,
            "forehead": (th < 30) & (zf > 0.1) & (zf < 0.6),
            "jaw": (th > 40) & (th < 95) & (zf < 0.0) & (zf > -0.6),
            "ear": ear & (zf > -0.15),
        }

    def test_ear_and_nape_regions_exist(self):
        for name, sel in self._regions().items():
            self.assertGreater(sel.sum(), 10, name)

    def test_every_style_covers_the_nape_and_behind_the_ears(self):
        from sasori import catalog
        regions = self._regions()
        for style in catalog.HAIR_STYLES:
            with self.subTest(style=style):
                m = self._coverage(style)
                self.assertGreater(m[regions["nape"]].mean(), 0.85, "bald nape")
                self.assertGreater(m[regions["behind_ear"]].mean(), 0.85, "bald behind the ear")
                self.assertLess(m[regions["forehead"]].mean(), 0.05, "hair on the forehead")
                self.assertLess(m[regions["jaw"]].mean(), 0.05, "hair on the jaw or the side of the neck")
                spec = catalog.HAIR_STYLES[style]
                if not spec.get("length") and not spec.get("round"):  # hanging hair and an afro do cover them
                    self.assertLess(m[regions["ear"]].mean(), 0.1, "hair over the ear")

    def test_nape_hair_lies_on_the_neck(self):
        """The base layer under the skull follows the hollow of the nape instead of bridging it."""
        from sasori.blender import garments, hair, util
        import bpy as _bpy
        h = hair.make(self.res, self.body, "short")
        try:
            bvh = garments.body_bvh(self.body)
            co = util.get_coords(h)
            base = np.zeros(len(co), dtype=bool)
            for p in h.data.polygons:
                if p.material_index == 0:
                    base[list(p.vertices)] = True
            _, _, _, z_ref, z_top, yc = hair._head_frame(self.res, self.body)
            low = base & (co[:, 2] < z_ref - 0.1 * (z_top - z_ref)) & (co[:, 1] > yc)
            self.assertGreater(low.sum(), 20)
            from mathutils import Vector
            gaps = [bvh.find_nearest(Vector(p))[3] for p in co[low]]
            self.assertLess(max(gaps), 0.02)
        finally:
            _bpy.data.objects.remove(h, do_unlink=True)


if __name__ == "__main__":
    unittest.main()
