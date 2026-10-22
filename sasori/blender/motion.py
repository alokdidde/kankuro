"""What the character adds on top of a Mesh2Motion clip, baked into the clip's action:

* secondary motion on extra bone chains (a tail, a braid, an earring): a damped spring that follows
  the body with lag and overshoot, kept out of the legs by capsules around the thighs and calves.
  Deterministic, and seamless on looping clips (simulated twice round the loop, the end eased into the
  start).
* grips: finger poses for held props, blended over the clip's own finger channels.
* a second hand on a two-hand prop: two-bone IK that keeps it on the prop, with a warning where the
  clip's arms can't reach.

The standard bones' channels are only touched for grips and two-hand IK; extra bones get their own."""
import math

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

FPS = 30.0
SUB = 4
LEGS = ("thigh_l", "thigh_r", "calf_l", "calf_r")


def _bags(act):
    try:
        return [cb for layer in act.layers for strip in layer.strips for cb in strip.channelbags]
    except AttributeError:
        return [act]


def _fcurves(act, bone, prop="rotation_quaternion"):
    path = f'pose.bones["{bone}"].{prop}'
    out = {}
    for bag in _bags(act):
        for fc in bag.fcurves:
            if fc.data_path == path:
                out[fc.array_index] = fc
    return out


def read_quats(act, bone, frames):
    """The clip's rotation of `bone` at each frame (identity where it has no channel)."""
    fcs = _fcurves(act, bone)
    q = np.zeros((len(frames), 4))
    q[:, 0] = 1
    for i, fc in fcs.items():
        q[:, i] = [fc.evaluate(f) for f in frames]
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def write_quats(act, arm, bone, frames, q):
    """Replace the clip's rotation channels of `bone` with keys q (len(frames) x 4), linear."""
    for bag in _bags(act):
        for fc in list(bag.fcurves):
            if fc.data_path == f'pose.bones["{bone}"].rotation_quaternion':
                bag.fcurves.remove(fc)
    for i in range(4):
        fc = act.fcurve_ensure_for_datablock(arm, f'pose.bones["{bone}"].rotation_quaternion', index=i,
                                             group_name=bone)
        fc.keyframe_points.add(len(frames))
        co = np.empty(len(frames) * 2)
        co[0::2] = frames
        co[1::2] = q[:, i]
        fc.keyframe_points.foreach_set("co", co)
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
        fc.update()


def _assign(arm, act):
    if arm.animation_data is None:
        arm.animation_data_create()
    ad = arm.animation_data
    ad.action = act
    if hasattr(ad, "action_slot") and len(act.slots):
        ad.action_slot = act.slots[0]


def sample(arm, act, bones):
    """Armature-space pose matrices {bone: (F, 4, 4)} of the clip at every frame, with frame numbers."""
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    frames = np.arange(f0, f1 + 1)
    _assign(arm, act)
    out = {b: np.zeros((len(frames), 4, 4)) for b in bones}
    sc = bpy.context.scene
    for i, f in enumerate(frames):
        sc.frame_set(int(f))
        for b in bones:
            out[b][i] = np.array(arm.pose.bones[b].matrix)
    return frames, out


def is_loop(mats, tol=0.01):
    for M in mats.values():
        if np.abs(M[0] - M[-1]).max() > tol:
            return False
    return True


def leg_capsules(b):
    """Radii of the thigh and calf capsules (median distance of the body vertices they move to the bone)."""
    from . import util
    co = util.get_coords(b.body)
    W = util.weight_matrix(b.body, list(LEGS))
    out = {}
    for j, n in enumerate(LEGS):
        sel = W[:, j] > 0.6
        bb = b.arm.data.bones[n]
        h, t = np.array(bb.head_local), np.array(bb.tail_local)
        ab = t - h
        p = co[sel] - h
        tt = np.clip(p @ ab / (ab @ ab), 0, 1)
        out[n] = float(np.median(np.linalg.norm(p - tt[:, None] * ab, axis=1))) if sel.any() else 0.06
    return out


def _push_capsule(x, a, bvec, r):
    ab = bvec - a
    t = np.clip(((x - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
    c = a + t[:, None] * ab
    d = x - c
    dist = np.linalg.norm(d, axis=1)
    m = (dist < r) & (dist > 1e-9)
    x[m] = c[m] + d[m] / dist[m, None] * r
    return x


def simulate_chain(arm, ch, frames, mats, caps, loop):
    """Joint positions (F, n+1, 3) of a chain over the clip."""
    bones = [arm.data.bones[n] for n in ch["bones"]]
    parent = arm.data.bones[ch["parent"]]
    Pr = np.array(parent.matrix_local)
    joints = [np.array(bones[0].head_local)] + [np.array(bb.tail_local) for bb in bones]
    q = [np.linalg.inv(Pr) @ np.append(j, 1.0) for j in joints]  # rest joints in the parent's space
    L = np.array([np.linalg.norm(joints[k + 1] - joints[k]) for k in range(len(bones))])
    n = len(bones)
    sp = ch["spring"]
    k = float(sp["stiffness"]) * 0.25 * (1 - 0.6 * np.arange(n + 1) / max(n, 1))
    damp = 1 - float(sp["damping"]) * 0.15
    g = np.array([0, 0, -9.81 * float(sp.get("gravity", 1.0))]) * (1 / (FPS * SUB)) ** 2
    rad = float(ch.get("radius", 0.02))
    PM = mats[ch["parent"]]
    F = len(frames)

    def targets(i, s):
        M = PM[i - 1] + (PM[i] - PM[i - 1]) * s if i > 0 else PM[0]
        return np.array([(M @ qq)[:3] for qq in q])

    x = targets(0, 1.0)
    xp = x.copy()
    out = np.zeros((F, n + 1, 3))
    for rnd in range(2 if loop else 1):
        for i in range(F):
            for s in range(1, SUB + 1):
                T = targets(i, s / SUB) if (i > 0 or rnd > 0) else targets(0, 1.0)
                if i == 0 and rnd > 0:
                    T = targets(F - 1, 1.0) + (targets(0, 1.0) - targets(F - 1, 1.0)) * s / SUB
                v = (x - xp) * damp
                xp = x.copy()
                x = x + v + g
                x += k[:, None] * (T - x)
                x[0] = T[0]
                for leg in LEGS:
                    if leg in mats:
                        M = mats[leg][i]
                        bb = arm.data.bones[leg]
                        a = (M @ np.append(np.zeros(3), 1))[:3]
                        e = (M @ np.array([0, bb.length, 0, 1]))[:3]
                        x[1:] = _push_capsule(x[1:], a, e, caps[leg] + rad)
                for j in range(1, n + 1):  # keep the bone lengths
                    d = x[j] - x[j - 1]
                    x[j] = x[j - 1] + d / (np.linalg.norm(d) + 1e-12) * L[j - 1]
            out[i] = x
    if loop and F > 8:
        K = max(4, min(12, F // 4))
        for j in range(K):
            w = (j + 1) / (K + 1)
            w = w * w * (3 - 2 * w)
            out[F - K + j] = out[F - K + j] * (1 - w) + out[0] * w
    return out


def chain_rotations(arm, ch, mats, pos):
    """Pose quaternions (n, F, 4) that point each chain bone at its simulated joints."""
    names = ch["bones"]
    rest = {nm: np.array(arm.data.bones[nm].matrix_local) for nm in names}
    par = np.array(arm.data.bones[ch["parent"]].matrix_local)
    F = pos.shape[0]
    out = np.zeros((len(names), F, 4))
    for i in range(F):
        Mp, Rp = mats[ch["parent"]][i], par
        for k, nm in enumerate(names):
            rel = np.linalg.inv(Rp) @ rest[nm]
            base = Matrix((Mp @ rel).tolist())
            cur = base.to_3x3().col[1].normalized()
            want = Vector(pos[i, k + 1] - pos[i, k]).normalized()
            qw = cur.rotation_difference(want)
            br = base.to_quaternion()
            ql = br.inverted() @ qw @ br
            out[k, i] = tuple(ql)
            Mp = np.array(base @ ql.to_matrix().to_4x4())
            Rp = rest[nm]
    # keep each quaternion on the same side as the previous one (no flips in linear keys)
    for k in range(len(names)):
        for i in range(1, F):
            if out[k, i] @ out[k, i - 1] < 0:
                out[k, i] *= -1
    return out


def slerp(a, b, t):
    out = np.zeros_like(a)
    for i in range(len(a)):
        out[i] = tuple(Quaternion(a[i]).slerp(Quaternion(b), t))
    return out


def two_bone_ik(arm, side, mats, targets):
    """Upperarm/lowerarm rotations that put hand_<side>'s head on each target (bending in the plane the
    clip's elbow is in). Returns (q_upper, q_lower, misses, hand_base) with misses the distances it fell
    short and hand_base the hand's pose matrix before its own rotation, per frame."""
    bones = arm.data.bones
    up, lo, hd = bones[f"upperarm_{side}"], bones[f"lowerarm_{side}"], bones[f"hand_{side}"]
    cl = bones[f"clavicle_{side}"]
    rel_u = np.linalg.inv(np.array(cl.matrix_local)) @ np.array(up.matrix_local)
    rel_l = np.linalg.inv(np.array(up.matrix_local)) @ np.array(lo.matrix_local)
    a = (Vector(lo.head_local) - Vector(up.head_local)).length
    bl = (Vector(hd.head_local) - Vector(lo.head_local)).length
    rel_h = Matrix((np.linalg.inv(np.array(lo.matrix_local)) @ np.array(hd.matrix_local)).tolist())
    F = len(targets)
    qu, ql, miss = np.zeros((F, 4)), np.zeros((F, 4)), np.zeros(F)
    hand_base = np.zeros((F, 4, 4))
    for i in range(F):
        base_u = Matrix((mats[f"clavicle_{side}"][i] @ rel_u).tolist())
        S = base_u.translation.copy()
        T = Vector(targets[i])
        E0 = Vector(mats[f"lowerarm_{side}"][i][:3, 3])
        d = (T - S).length
        miss[i] = max(0.0, d - (a + bl) * 0.999)
        d = min(max(d, abs(a - bl) + 1e-4), (a + bl) * 0.999)
        u = (T - S).normalized()
        pole = (E0 - S) - u * (E0 - S).dot(u)
        if pole.length < 1e-6:
            pole = Vector((0, 0, -1)) - u * (-u.z)
        pole.normalize()
        ca = (a * a + d * d - bl * bl) / (2 * a * d)
        ang = math.acos(max(-1, min(1, ca)))
        E = S + (u * math.cos(ang) + pole * math.sin(ang)) * a
        br = base_u.to_quaternion()
        q1 = br.inverted() @ base_u.to_3x3().col[1].normalized().rotation_difference((E - S).normalized()) @ br
        Mu = base_u @ q1.to_matrix().to_4x4()
        base_l = Mu @ Matrix(rel_l.tolist())
        bl_q = base_l.to_quaternion()
        q2 = bl_q.inverted() @ base_l.to_3x3().col[1].normalized().rotation_difference((T - E).normalized()) @ bl_q
        qu[i], ql[i] = tuple(q1), tuple(q2)
        hand_base[i] = np.array(base_l @ q2.to_matrix().to_4x4() @ rel_h)
    for q in (qu, ql):
        for i in range(1, F):
            if q[i] @ q[i - 1] < 0:
                q[i] *= -1
    return qu, ql, miss, hand_base


def prepare(b, act, secondary=None):
    """Bake the character's extra motion into `act` (in place). secondary: chain ids to simulate
    (None = every enabled chain). Returns warnings."""
    arm = b.arm
    warnings = []
    chains = [c for c in getattr(b, "chains", []) if c.get("enabled", True)
              and (secondary is None or c["id"] in secondary)]
    grips = getattr(b, "grips", [])
    if not chains and not grips:
        return warnings
    need = set(LEGS)
    for c in chains:
        need.add(c["parent"])
    for g in grips:
        if g.get("second"):
            s = g["second"]
            a_ = g["anchor"]
            need |= {f"clavicle_{s}", f"lowerarm_{s}", f"clavicle_{a_}", f"lowerarm_{a_}", g["hold_bone"]}
    need = [n for n in need if n in arm.pose.bones]
    _assign(arm, act)
    # grips first: they change no bone the chains or the IK depend on
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    frames = np.arange(f0, f1 + 1)
    for g in grips:
        for bone, q in g["pose"].items():
            cur = read_quats(act, bone, frames)
            write_quats(act, arm, bone, frames, slerp(cur, q, float(g.get("weight", 1.0))))
    frames, mats = sample(arm, act, need)
    loop = is_loop({n: mats[n] for n in need if n in LEGS or n == "pelvis"})
    caps = getattr(b, "capsules", None) or {}
    for c in chains:
        pos = simulate_chain(arm, c, frames, mats, caps, loop)
        rots = chain_rotations(arm, c, mats, pos)
        for k, nm in enumerate(c["bones"]):
            write_quats(act, arm, nm, frames, rots[k])
    for g in grips:
        if not g.get("second"):
            continue
        an, s = g["anchor"], g["second"]
        # the anchor hand brings the prop to its hold point (in front of the chest, or the mouth for a
        # flute), turned so the prop runs across towards the other hand, palm to the body
        H = mats[g["hold_bone"]]
        hold = np.array([(M @ np.append(g["hold"], 1))[:3] for M in H])
        qu, ql, miss0, hb = two_bone_ik(arm, an, mats, hold)
        write_quats(act, arm, f"upperarm_{an}", frames, qu)
        write_quats(act, arm, f"lowerarm_{an}", frames, ql)
        Rw = Matrix(np.array(g["socket_world"]).tolist())  # wanted socket orientation, character space
        rel = Matrix(np.array(g["socket_in_hand"]).tolist())
        qh = np.zeros((len(frames), 4))
        S = np.zeros((len(frames), 4, 4))
        for i in range(len(frames)):
            Bh = Matrix(hb[i].tolist())
            Mbody = Matrix(H[i].tolist()).to_quaternion()  # turn with the body
            want = (Mbody.to_matrix() @ Rw @ rel.to_3x3().inverted()).to_quaternion()
            q = Bh.to_quaternion().inverted() @ want
            qh[i] = tuple(q)
            S[i] = np.array(Bh @ q.to_matrix().to_4x4() @ rel)
        for i in range(1, len(frames)):
            if qh[i] @ qh[i - 1] < 0:
                qh[i] *= -1
        write_quats(act, arm, f"hand_{an}", frames, qh)
        tgt = np.array([(M @ np.append(g["target"], 1))[:3] for M in S])
        qu, ql, miss, _ = two_bone_ik(arm, s, mats, tgt)
        write_quats(act, arm, f"upperarm_{s}", frames, qu)
        write_quats(act, arm, f"lowerarm_{s}", frames, ql)
        miss = np.maximum(miss, miss0)
        worst = float(miss.max())
        if worst > 0.01:
            warnings.append({"code": "second_hand_unreachable", "prop": g["id"], "clip": act.name,
                             "max_miss_m": round(worst, 3),
                             "message": f"{act.name}: the {s} hand can't reach prop '{g['id']}' on "
                                        f"{int((miss > 0.01).sum())} of {len(miss)} frames (up to {worst:.2f} m short)"})
    arm.animation_data.action = None
    return warnings
