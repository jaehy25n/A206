"""CSV recording format shared by teach_node and the CLI.

    # omx_teach recording v1
    # name: cup1
    # created: 2026-09-23T11:50:00
    # joints: joint1,joint2,joint3,joint4,joint5,gripper_joint_1
    t,joint1,joint2,joint3,joint4,joint5,gripper_joint_1
    0.000000,0.0123,...

t is seconds from the first sample (header stamp of /joint_states), positions in
radians.  A sibling <name>_ee.csv (t,x,y,z,qx,qy,qz,qw,gripper_width) is written
when the omx_control kinematics are importable (position and jaw width in metres).
"""

import csv
import datetime
import glob
import os

import numpy as np

FORMAT_TAG = 'omx_teach recording v1'


def recordings_dir(path):
    d = os.path.expanduser(path)
    os.makedirs(d, exist_ok=True)
    return d


def resolve(name, directory):
    """name -> absolute csv path. Empty name -> newest recording in directory."""
    if not name:
        cands = [p for p in glob.glob(os.path.join(directory, '*.csv'))
                 if not p.endswith('_ee.csv')]
        if not cands:
            raise FileNotFoundError(f'no recordings in {directory}')
        return max(cands, key=os.path.getmtime)
    if os.path.isabs(name) or os.sep in name:
        return name if name.endswith('.csv') else name + '.csv'
    stem = name[:-4] if name.endswith('.csv') else name
    return os.path.join(directory, stem + '.csv')


def list_recordings(directory):
    out = []
    for p in sorted(glob.glob(os.path.join(directory, '*.csv')), key=os.path.getmtime):
        if p.endswith('_ee.csv'):
            continue
        try:
            t, _, _ = load(p)
            out.append((os.path.basename(p)[:-4], len(t), float(t[-1]) if len(t) else 0.0))
        except Exception:  # noqa: BLE001
            out.append((os.path.basename(p)[:-4], -1, 0.0))
    return out


def save(path, name, joint_names, t, q, ee=None):
    """t [N], q [N, J] -> csv. ee: optional [N, 8] (x y z qx qy qz qw width)."""
    t = np.asarray(t, float)
    q = np.asarray(q, float)
    created = datetime.datetime.now().isoformat(timespec='seconds')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        f.write(f'# {FORMAT_TAG}\n# name: {name}\n# created: {created}\n')
        f.write(f'# joints: {",".join(joint_names)}\n')
        f.write(f'# samples: {len(t)}  duration_s: {t[-1] - t[0] if len(t) else 0.0:.3f}\n')
        w = csv.writer(f)
        w.writerow(['t'] + list(joint_names))
        for ti, qi in zip(t, q):
            w.writerow([f'{ti:.6f}'] + [f'{v:.6f}' for v in qi])
    if ee is not None:
        ee_path = path[:-4] + '_ee.csv'
        with open(ee_path, 'w', newline='', encoding='utf-8') as f:
            f.write(f'# {FORMAT_TAG} (tcp pose in base_link, from FK)\n# name: {name}\n')
            w = csv.writer(f)
            w.writerow(['t', 'x', 'y', 'z', 'qx', 'qy', 'qz', 'qw', 'gripper_width'])
            for ti, row in zip(t, ee):
                w.writerow([f'{ti:.6f}'] + [f'{v:.6f}' for v in row])
        return path, ee_path
    return path, None


def load(path):
    """csv -> (t [N], q [N, J], joint_names)."""
    joint_names = None
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                if line.startswith('# joints:'):
                    joint_names = [s.strip() for s in line[len('# joints:'):].split(',')]
                continue
            if line.startswith('t,'):
                if joint_names is None:
                    joint_names = line.split(',')[1:]
                continue
            rows.append([float(v) for v in line.split(',')])
    if not rows:
        raise ValueError(f'{path}: no samples')
    data = np.asarray(rows, float)
    t, q = data[:, 0], data[:, 1:]
    if joint_names is None or len(joint_names) != q.shape[1]:
        raise ValueError(f'{path}: joint header does not match {q.shape[1]} columns')
    if np.any(np.diff(t) < 0):
        raise ValueError(f'{path}: time column is not monotonic')
    return t, q, joint_names
