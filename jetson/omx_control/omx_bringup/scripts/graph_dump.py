#!/usr/bin/env python3
"""Dump the live ROS 2 graph in rqt_graph style (nodes = ellipses, topics = boxes).

    ros2 run omx_bringup graph_dump.py -o rosgraph.dot --png

Hidden/infrastructure topics (/rosout, /parameter_events) and CLI helper nodes
are skipped so the picture matches what rqt_graph shows with its defaults.
"""

import argparse
import re
import subprocess
import sys
import time

import rclpy

HIDDEN_TOPICS = {'/rosout', '/parameter_events'}
HIDDEN_NODE_PREFIXES = ('_', 'rqt_', 'ros2cli', 'transform_listener_impl')


def _id(s):
    return 'n_' + re.sub(r'[^A-Za-z0-9_]', '_', s)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-o', '--out', default='rosgraph.dot')
    ap.add_argument('--png', action='store_true', help='also render <out>.png with dot')
    ap.add_argument('--wait', type=float, default=2.0, help='discovery time [s]')
    ap.add_argument('--no-types', action='store_true', help='omit message types on topics')
    args = ap.parse_args()

    rclpy.init()
    node = rclpy.create_node('_graph_dump')
    end = time.time() + args.wait
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.1)

    nodes = []
    pubs, subs, types = [], [], {}
    for name, ns in node.get_node_names_and_namespaces():
        if name.startswith(HIDDEN_NODE_PREFIXES):
            continue
        full = ('/' + name) if ns == '/' else (ns.rstrip('/') + '/' + name)
        nodes.append(full)
        for topic, tps in node.get_publisher_names_and_types_by_node(name, ns):
            if topic in HIDDEN_TOPICS or '/_' in topic:
                continue
            pubs.append((full, topic))
            types.setdefault(topic, tps[0] if tps else '')
        for topic, tps in node.get_subscriber_names_and_types_by_node(name, ns):
            if topic in HIDDEN_TOPICS or '/_' in topic:
                continue
            subs.append((full, topic))
            types.setdefault(topic, tps[0] if tps else '')
    node.destroy_node()
    rclpy.shutdown()

    topics = sorted({t for _, t in pubs} | {t for _, t in subs})
    lines = ['digraph rosgraph {', '  rankdir=LR;',
             '  node [fontname="Helvetica", fontsize=10];',
             '  edge [color="#555555"];']
    for n in sorted(nodes):
        lines.append(f'  {_id(n)} [shape=ellipse, style=filled, fillcolor="#cfe2ff", label="{n}"];')
    for t in topics:
        label = t if args.no_types else f'{t}\\n{types.get(t, "")}'
        lines.append(f'  {_id("t" + t)} [shape=box, style=filled, fillcolor="white", label="{label}"];')
    for n, t in sorted(set(pubs)):
        lines.append(f'  {_id(n)} -> {_id("t" + t)};')
    for n, t in sorted(set(subs)):
        lines.append(f'  {_id("t" + t)} -> {_id(n)};')
    lines.append('}')

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'{len(nodes)} nodes, {len(topics)} topics -> {args.out}')

    if args.png:
        png = re.sub(r'\.dot$', '', args.out) + '.png'
        try:
            subprocess.run(['dot', '-Tpng', args.out, '-o', png], check=True)
            print(f'rendered {png}')
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f'dot failed: {exc}', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
