"""Props held in the hand: a bow, a staff, a flute, a tool.

A prop is rigid and hangs from a socket bone, prop_l or prop_r, under hand_l / hand_r (an optional extra
bone: engines and Blender get a clean, swappable attach point). Its grip is a finger pose solved on the
rest pose against the prop itself (contact grips curl each finger joint until the finger touches it),
then baked over the finger channels of every clip (motion.py). A two-hand prop keeps the other hand on
it with IK."""
import math

import bmesh
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

from .. import catalog
from . import accessories, extras, garments, util

FINGERS = catalog.FINGERS


def _bone(arm, n):
    return arm.data.bones[n]


def palm_frame(arm, body_obj, side):
    """(wrist, palm centre on the skin, palm normal, finger direction, index->pinky direction)."""
    hb, mid = _bone(arm, f"hand_{side}"), _bone(arm, f"middle_01_{side}")
    idx, pk = _bone(arm, f"index_01_{side}"), _bone(arm, f"pinky_01_{side}")
    wrist = np.array(hb.head_local)
    fdir = np.array(mid.tail_local - mid.head_local)
    fdir /= np.linalg.norm(fdir)
    across = np.array(pk.head_local - idx.head_local)
    across -= fdir * (across @ fdir)
    across /= np.linalg.norm(across)
    n = np.array(mid.matrix_local.to_3x3().col[2])  # finger bones' Z points to the palm side
    n -= fdir * (n @ fdir)
    n /= np.linalg.norm(n)
    c = wrist + 0.8 * (np.array(mid.head_local) - wrist)
    bvh = garments.body_bvh(body_obj)
    hit = bvh.ray_cast(Vector(c + n * 0.08), Vector(-n), 0.16)
    surf = np.array(hit[0]) if hit[0] is not None else c + n * 0.015
    return wrist, surf, n, fdir, across


def _cylinder(name, center, axis, radius, length, along, sides=28):
    """A capped cylinder: `along` of its length towards +axis from the center, the rest towards -axis."""
    a = Vector(axis).normalized()
    u = a.orthogonal().normalized()
    v = a.cross(u)
    c = Vector(center)
    p0, p1 = c - a * length * (1 - along), c + a * length * along
    verts, faces = [], []
    for end in (p0, p1):
        for j in range(sides):
            t = 2 * math.pi * j / sides
            verts.append(end + (u * math.cos(t) + v * math.sin(t)) * radius)
    for j in range(sides):
        j2 = (j + 1) % sides
        faces.append([j, j2, sides + j2, sides + j])
    faces.append(list(range(sides))[::-1])
    faces.append(list(range(sides, 2 * sides)))
    obj = util.make_mesh(name, np.array(verts), faces)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # a few rings along the length so it bends nicely in viewers' smooth shading
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if abs((e.verts[0].co - e.verts[1].co).normalized().dot(a)) > 0.99],
                              cuts=max(1, int(length / 0.05)), use_grid_fill=False)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    for p in obj.data.polygons:
        p.use_smooth = len(p.vertices) == 4
    return obj


def _finger_radius(b, bone):
    """Median distance of the body vertices `bone` moves from its axis (how thick the finger is)."""
    bb = _bone(b.arm, bone)
    sel = util.weight_matrix(b.body, [bone])[:, 0] > 0.5
    if not sel.any():
        return 0.008
    h, t = np.array(bb.head_local), np.array(bb.tail_local)
    ab = t - h
    p = util.get_coords(b.body)[sel] - h
    tt = np.clip(p @ ab / (ab @ ab), 0, 1)
    return float(np.median(np.linalg.norm(p - tt[:, None] * ab, axis=1)))


class _Finger:
    """Forward kinematics of one finger (three bones and a tip) in the rest pose."""

    def __init__(self, arm, side, name):
        pre = f"{name}_0"
        self.names = [f"{pre}{k}_{side}" for k in (1, 2, 3)]
        bs = [_bone(arm, n) for n in self.names]
        leaf = _bone(arm, f"{pre}4_leaf_{side}")
        self.rest = [Matrix(b.matrix_local) for b in bs]
        tip = Vector(leaf.head_local) + (Vector(leaf.tail_local) - Vector(leaf.head_local)) * 0.6
        self.points = [Vector(b.head_local) for b in bs] + [Vector(bs[2].tail_local), tip]
        self.axis = (1, 0, 0)

    def joints(self, angles):
        """World joint positions for curl angles (radians) about each bone's local axis."""
        pts = [p.copy() for p in self.points]
        for k in range(3):
            # bone k's axis, already moved by the joints before it
            M = self.rest[k]
            ax = (self._acc_rot(angles, k) @ (M.to_3x3() @ Vector(self.axis))).normalized()
            R = Matrix.Rotation(angles[k], 3, ax)
            piv = pts[k]
            for j in range(k + 1, len(pts)):
                pts[j] = piv + R @ (pts[j] - piv)
        return pts

    def _acc_rot(self, angles, k):
        R = Matrix.Identity(3)
        for j in range(k):
            ax = (R @ (self.rest[j].to_3x3() @ Vector(self.axis))).normalized()
            R = Matrix.Rotation(angles[j], 3, ax) @ R
        return R

    def samples(self, pts, first=0):
        """(point, segment) pairs along the finger from segment `first` to the tip."""
        out = []
        for k in range(first, len(pts) - 1):
            for t in (0.25, 0.5, 0.75, 1.0):
                out.append((pts[k] + (pts[k + 1] - pts[k]) * t, k))
        return out


def _signed(bvh, p):
    loc, nrm, _, dist = bvh.find_nearest(p)
    if loc is None:
        return 1.0
    d = (p - loc).length
    return d if (p - loc).dot(nrm) >= 0 else -d


def _touch(f, bvh, angles, first, r):
    """Whether the finger is within r[segment] (its flesh radius) of the prop anywhere past `first`."""
    return any(_signed(bvh, p) < r[min(k, len(r) - 1)] for p, k in f.samples(f.joints(angles), first))


def _orient(f, toward, sign_axes=((1, 0, 0), (-1, 0, 0))):
    """Pick the curl axis that moves the tip towards `toward`."""
    best, best_d = sign_axes[0], None
    for ax in sign_axes:
        f.axis = ax
        d = (f.joints([0.2, 0.2, 0.2])[-1] - toward).length
        if best_d is None or d < best_d:
            best, best_d = ax, d
    f.axis = best


def _solve_contact(f, bvh, r, maxdeg, step=2.0, open_deg=40.0, first=0):
    """Curl all three joints together (in proportion to their limits) until the finger touches, then
    the middle and tip joints on their own, so the finger wraps round the prop. A finger that starts
    inside the prop (a thumb lying over the grip) first opens at the knuckle until it is clear.
    Segments before `first` are not checked (the thumb's base is palm flesh, pressed on the grip)."""
    ang = [0.0, 0.0, 0.0]
    if bvh is None:
        return ang
    lim = [math.radians(m) for m in maxdeg]
    s = math.radians(step)
    while _touch(f, bvh, ang, first, r) and ang[0] > -math.radians(open_deg):
        ang[0] -= s
    base = list(ang)
    n = max(1, int(max(maxdeg) / step))
    for i in range(1, n + 1):
        trial = [base[k] + (lim[k] - max(base[k], 0.0)) * i / n if k else
                 base[0] + (lim[0] - base[0]) * i / n for k in range(3)]
        if _touch(f, bvh, trial, first, r):
            break
        ang = trial
    for k in (1, 2):
        while ang[k] + s <= lim[k]:
            trial = list(ang)
            trial[k] += s
            if _touch(f, bvh, trial, max(k, first), r):
                break
            ang = trial
    return ang


def solve_grip(b, side, grip, bvh, toward):
    """Local pose quaternions {bone: (w, x, y, z)} for a grip preset, solved against `bvh` (the prop)."""
    g = catalog.GRIPS[grip]
    arm = b.arm
    pose = {}
    for name in FINGERS + ("thumb",):
        f = _Finger(arm, side, name)
        thumb = name == "thumb"
        _orient(f, Vector(toward), ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)) if thumb else ((1, 0, 0), (-1, 0, 0)))
        spec = g["thumb"] if thumb else g.get(name, g["fingers"])
        if spec == "contact" and (thumb or "only" not in g or name in g["only"]):
            r = [_finger_radius(b, n) * 1.05 for n in f.names]
            mx = [50, 50, 60] if thumb else g.get("max", [90, 100, 80])
            ang = _solve_contact(f, bvh, r, mx, first=1 if thumb else 0)
        elif spec == "contact":
            ang = [math.radians(a) for a in g.get("rest", [30, 45, 30])]
        else:
            ang = [math.radians(a) for a in spec]
        for nm, a in zip(f.names, ang):
            pose[nm] = tuple(Quaternion(Vector(f.axis), a))
    return pose


HAND_JOINTS = ("hand", "thumb_01", "index_01", "middle_01", "ring_01", "pinky_01", "middle_03")


def hand_transform(ref_arm, arm, side):
    """Similarity transform from the reference body's hand to this one, fitted to the hand's joints (so it
    also works on an autorigged character, which has no reference-body correspondence)."""
    src = np.array([ref_arm.data.bones[f"{n}_{side}"].head_local for n in HAND_JOINTS])
    dst = np.array([arm.data.bones[f"{n}_{side}"].head_local for n in HAND_JOINTS])
    return accessories._umeyama(src, dst)


def _bvh_of(obj):
    co = util.get_coords(obj)
    return BVHTree.FromPolygons([Vector(c) for c in co], [list(p.vertices) for p in obj.data.polygons])


def build_all(b, spec, project):
    import os

    from . import build, materials
    from .. import matlib
    items = spec.get("props") or []
    if not items:
        return
    arm = b.arm
    sockets, made = {}, []
    for pr in items:
        hand = pr.get("hand", "r")
        side = pr.get("anchor", "r") if hand == "both" else hand
        wrist, surf, n, fdir, across = palm_frame(arm, b.body, side)
        if pr.get("file"):
            ref = build.reference_body()
            obj = build.import_mesh_file(os.path.join(project, pr["file"]), pr["id"])
            s, R, t = hand_transform(ref.arm, arm, side)
            co = util.get_coords(obj)
            co = s * co @ R.T + t
            grip_pt = surf + n * 0.015
            keep = len(obj.data.materials) > 0
        else:
            d = catalog.PROPS[pr["builtin"]]
            rad = d["radius"]
            grip_pt = surf + n * (rad + 0.002)
            # across the palm (towards the index finger is -across), tilted along the fingers the way a
            # real grip lies diagonally across the palm
            tilt = math.radians(d.get("tilt", 15))
            ax = -across * math.cos(tilt) + fdir * math.sin(tilt)
            obj = _cylinder(pr["id"], grip_pt, ax, rad, d["length"], d.get("along", 0.5))
            co = util.get_coords(obj)
            keep = False
            pr = {**d, **pr}
        obj.name = pr["id"]
        cen = grip_pt
        co = (co - cen) * float(pr.get("scale", 1.0)) @ accessories._euler(pr.get("rotate", (0, 0, 0))).T + cen
        co = co + np.array(pr.get("offset", (0, 0, 0)), float)
        util.set_coords(obj, co)
        sock = f"prop_{side}"
        if sock not in sockets:
            sockets[sock] = {"name": sock, "parent": f"hand_{side}", "head": grip_pt, "tail": grip_pt + fdir * 0.06,
                             "deform": True, "roll": n}
        util.set_weight_matrix(obj, np.ones((len(co), 1)), [sock])
        if pr.get("material") or pr.get("color") or not keep:
            obj.data.materials.clear()
            if pr.get("material"):
                kw = materials.preset_kwargs(matlib.resolve(pr["material"], pr.get("color"), pr.get("roughness")))
            else:
                kw = dict(color=pr.get("color") or "#7a5a3a", roughness=pr.get("roughness", 0.6))
            obj.data.materials.append(materials.make(f"Prop_{pr['id']}", **kw))
        util.add_armature_modifier(obj, arm)
        obj["prop_id"] = pr["id"]
        b.meshes.append(obj)
        made.append((pr, obj, side, hand, grip_pt, across))
    extras.add_bones(arm, list(sockets.values()))
    for pr, obj, side, hand, grip_pt, across in made:
        bvh = _bvh_of(obj)
        grip = pr.get("grip", "power")
        pose = solve_grip(b, side, grip, bvh, grip_pt)
        g = {"id": pr["id"], "pose": pose, "weight": float(pr.get("grip_weight", 1.0)), "anchor": side}
        if hand == "both":
            other = "l" if side == "r" else "r"
            reach = float(pr.get("reach", -0.3))
            # the other hand holds the prop `reach` along it towards the anchor's index finger: solve its
            # grip on a stand-in of the same thickness laid across its own palm
            co = util.get_coords(obj)
            axis = -across
            rel = co - grip_pt
            near = np.abs(rel @ axis - reach) < 0.02
            rad = float(np.median(np.linalg.norm(rel[near] - np.outer(rel[near] @ axis, axis), axis=1))) if near.any() else 0.015
            w2, s2, n2, f2, a2 = palm_frame(arm, b.body, other)
            gp2 = s2 + n2 * (rad + 0.002)
            stand = _cylinder("_grip_stand_in", gp2, a2, rad, 0.2, 0.5)
            pose.update(solve_grip(b, other, grip, _bvh_of(stand), gp2))
            _remove(stand)
            bones = arm.data.bones
            S = bones[f"prop_{side}"].matrix_local
            Hd = bones[f"hand_{side}"].matrix_local
            # where the anchor's wrist goes, in the hold bone's space
            hb = bones[pr.get("hold_bone", "spine_03")]
            off = np.array(pr.get("hold", (-0.12, -0.3, 0.0)), float)
            if side == "l":
                off[0] = -off[0]
            hold = hb.matrix_local.inverted() @ Vector(np.array(hb.head_local) + off)
            # the socket turned so the prop runs across the body (its index-finger end away from the
            # other hand), palm to the body: the fingers point up and wrap over it
            Rs = S.to_3x3()
            ax_l = Rs.transposed() @ Vector(axis)
            n_l = Rs.transposed() @ Vector(_palm_normal(arm, side))
            a_w = Vector((-1, 0, 0)) if side == "r" else Vector((1, 0, 0))
            want = _frame(a_w, Vector((0, 1, 0))) @ _frame(ax_l, n_l).transposed()
            # the other wrist sits off the prop like the anchor's, facing the other way along it
            w = S.inverted() @ bones[f"hand_{side}"].head_local
            axn = ax_l.normalized()
            w_other = w - axn * (2 * w.dot(axn))
            g.update(second=other, target=np.array(S.inverted() @ Vector(grip_pt + axis * reach) + w_other),
                     hold_bone=hb.name, hold=np.array(hold),
                     socket_world=np.array(hb.matrix_local.to_3x3().transposed() @ want),
                     socket_in_hand=np.array(Hd.inverted() @ S))
        b.grips.append(g)


def _palm_normal(arm, side):
    m = _bone(arm, f"middle_01_{side}")
    return np.array(m.matrix_local.to_3x3().col[2])


def _frame(a, n):
    """Rotation whose columns are a, n (made perpendicular to a) and a x n."""
    a = a.normalized()
    n = (n - a * n.dot(a)).normalized()
    return Matrix((a, n, a.cross(n))).transposed()


def _remove(obj):
    import bpy
    bpy.data.objects.remove(obj, do_unlink=True)


def penetration(b, hold_bones=None):
    """Props that cut into the body (outside the hands holding them) in the current pose."""
    import bpy
    dg = bpy.context.evaluated_depsgraph_get()

    def ev_bvh(o, keep=None):
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        polys = [list(p.vertices) for p in me.polygons]
        ev.to_mesh_clear()
        if keep is not None:
            polys = [p for p in polys if all(keep[v] for v in p)]
        return BVHTree.FromPolygons([Vector(c) for c in co], polys), co, polys

    def inside(bvh, polys, co):
        """Some prop vertex is under the skin away from the hands (a prop sunk wholly into the body
        crosses no surface)."""
        for c in co[:: max(1, len(co) // 200)]:
            loc, nrm, i, d = bvh.find_nearest(Vector(c))
            s = (Vector(c) - loc).dot(nrm) if loc is not None else 0.0
            # under the skin: behind the nearest face and roughly along its normal (a point beside an
            # edge of the skin is behind the face's plane too)
            if d < 0.15 and s < -0.005 and -s > 0.7 * d and all(keep[v] for v in polys[i]):
                return True
        return False

    names = [bn for bn in b.res.bones if bn.startswith(("hand_", "thumb_", "index_", "middle_", "ring_", "pinky_",
                                                          "lowerarm_"))]
    W = util.weight_matrix(b.body, names)
    keep = W.sum(1) < 0.3
    body = ev_bvh(b.body, keep)[0]
    whole, _, polys = ev_bvh(b.body)
    out = []
    for m in b.meshes:
        if not m.get("prop_id"):
            continue
        pb, co, _ = ev_bvh(m)
        if body.overlap(pb) or inside(whole, polys, co):
            out.append({"code": "prop_penetration", "prop": m["prop_id"],
                        "message": f"prop '{m['prop_id']}' cuts into the body in this pose; adjust it with "
                                   "`prop set --offset/--rotate`"})
    return out


def pose_grips(b):
    """Show the grips on the rest pose (for renders without a clip)."""
    import bpy
    for g in b.grips:
        for bone, q in g["pose"].items():
            pb = b.arm.pose.bones[bone]
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = Quaternion((1, 0, 0, 0)).slerp(Quaternion(q), g.get("weight", 1.0))
    bpy.context.view_layer.update()
