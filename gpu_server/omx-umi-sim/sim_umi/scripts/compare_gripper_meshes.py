"""Are the printed fingers (gripper_l/r) the same part as the URDF's 07/08?

    python sim_umi/scripts/compare_gripper_meshes.py

Not a bounding-box comparison: those matched to a millimetre while the meshes
sat in different frames and different units, which is exactly how a wrong
conclusion gets drawn. This aligns the two properly and then measures the
surfaces against each other.

  units      07/08 are millimetres (URDF scale 0.001), gripper_l/r are metres
             -- at 0.001 they compile to a 0.07 mm part, which is why an
             earlier render of them came out black.
  alignment  every one of the 48 axis-aligned frames (24 rotations, with and
             without a mirror), centroid to centroid, then ICP refinement.
             A mirror winning is a real answer: it means the part is the
             other hand.
  distance   symmetric Chamfer over area-weighted surface samples, plus the
             95th percentile and the max, in millimetres.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import itertools
import pathlib

import click
import mujoco
import numpy as np
from scipy.spatial import cKDTree

SIM = pathlib.Path(ROOT) / "sim_umi"
MESHDIR = SIM / "assets" / "omx"


def load(fname, scale):
    xml = (f'<mujoco><compiler meshdir="{MESHDIR}"/><asset>'
           f'<mesh name="m" file="{fname}" scale="{scale} {scale} {scale}"/>'
           f'</asset><worldbody><geom type="mesh" mesh="m"/></worldbody></mujoco>')
    tmp = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "_cmp_mesh.xml"
    tmp.write_text(xml)
    m = mujoco.MjModel.from_xml_path(str(tmp))
    v = m.mesh_vert[:m.mesh_vertnum[0]].astype(np.float64)
    f = m.mesh_face[:m.mesh_facenum[0]].astype(np.int64)
    return v, f


def sample_surface(v, f, n, rng):
    a, b, cc = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, cc - a), axis=1)
    idx = rng.choice(len(f), size=n, p=area / area.sum())
    u = rng.random((n, 1))
    w = rng.random((n, 1))
    over = (u + w) > 1
    u[over], w[over] = 1 - u[over], 1 - w[over]
    return a[idx] + u * (b[idx] - a[idx]) + w * (cc[idx] - a[idx])


def axis_frames():
    """The 24 rotations of the cube, then each of them mirrored."""
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            R = np.zeros((3, 3))
            for i, p in enumerate(perm):
                R[i, p] = signs[i]
            out.append(R)
    return out


def icp(src, dst_tree, dst_pts, R, t, iters=25):
    for _ in range(iters):
        p = src @ R.T + t
        _, idx = dst_tree.query(p)
        q = dst_pts[idx]
        pc, qc = src.mean(0), q.mean(0)
        H = (src - pc).T @ (q - qc)
        U, _, Vt = np.linalg.svd(H)
        d = np.sign(np.linalg.det(Vt.T @ U.T))
        Rn = Vt.T @ np.diag([1, 1, d]) @ U.T
        if np.sign(np.linalg.det(R)) < 0:          # keep the mirror if we had one
            Rn = Rn @ np.diag([1, 1, -1])
            Rn = Rn if np.sign(np.linalg.det(Rn)) < 0 else Rn @ np.diag([1, 1, -1])
        R, t = Rn, qc - Rn @ pc
    return R, t


def chamfer(a, b_tree, b_pts, a_tree):
    d1, _ = b_tree.query(a)
    d2, _ = a_tree.query(b_pts)
    both = np.concatenate([d1, d2])
    return both.mean(), np.percentile(both, 95), both.max()


@click.command()
@click.option("-n", "--n-points", default=20000, type=int)
def main(n_points):
    rng = np.random.default_rng(0)
    parts = {
        "07_motorized": load("follower_07_gripper_motorized.stl", 0.001),
        "08_gear": load("follower_08_gripper_gear.stl", 0.001),
        "gripper_l": load("follower_gripper_l.stl", 1.0),
        "gripper_r": load("follower_gripper_r.stl", 1.0),
    }
    pts = {}
    for k, (v, f) in parts.items():
        pts[k] = sample_surface(v, f, n_points, rng)
        lo, hi = pts[k].min(0) * 1000, pts[k].max(0) * 1000
        click.echo(f"  {k:14s} {len(v):5d} verts  extent mm "
                   f"{hi[0]-lo[0]:6.2f} x {hi[1]-lo[1]:6.2f} x {hi[2]-lo[2]:6.2f}")

    trees = {k: cKDTree(p) for k, p in pts.items()}
    frames = axis_frames()
    for src, dst in (("gripper_l", "07_motorized"), ("gripper_l", "08_gear"),
                     ("gripper_r", "07_motorized"), ("gripper_r", "08_gear")):
        a, b = pts[src], pts[dst]
        ac, bc = a.mean(0), b.mean(0)
        best = None
        coarse = rng.choice(len(a), 2500, replace=False)
        for R0 in frames:
            for mirror in (np.eye(3), np.diag([-1.0, 1.0, 1.0])):
                R = mirror @ R0
                t = bc - R @ ac
                d, _ = trees[dst].query(a[coarse] @ R.T + t)
                sc = d.mean()
                if best is None or sc < best[0]:
                    best = (sc, R, t)
        _, R, t = best
        R, t = icp(a, trees[dst], b, R, t)
        moved = a @ R.T + t
        mtree = cKDTree(moved)
        mean, p95, mx = chamfer(moved, trees[dst], b, mtree)
        det = np.linalg.det(R)
        click.secho(f"\n{src}  ->  {dst}", bold=True)
        click.echo(f"   alignment: det(R) = {det:+.3f} "
                   f"({'MIRRORED' if det < 0 else 'rotation only'})")
        click.echo(f"   chamfer mean {mean*1000:6.3f} mm   p95 {p95*1000:6.3f} mm"
                   f"   max {mx*1000:6.3f} mm")
        lo, hi = moved.min(0) * 1000, (moved).max(0) * 1000
        blo, bhi = b.min(0) * 1000, b.max(0) * 1000
        click.echo(f"   transformed bbox  {np.round(lo,2)} .. {np.round(hi,2)}")
        click.echo(f"   target      bbox  {np.round(blo,2)} .. {np.round(bhi,2)}")
        click.secho("   -> same part" if p95 < 0.001 else
                    "   -> NOT the same part", bold=True,
                    fg="green" if p95 < 0.001 else "red")


if __name__ == "__main__":
    main()
