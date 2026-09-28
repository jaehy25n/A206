"""Generate the bin's ArUco marker textures.

The real bin is a 120 mm white PLA cube with the top open and a 60 mm ArUco
marker on each of the four sides, IDs 0-3, printed from chev.me/arucogen and
stuck slightly above centre.

    python sim_umi/scripts/make_aruco_assets.py --dict 4x4_50

The dictionary matters: the same ID is a different bit pattern in every
dictionary, so a sim marker from the wrong one is a different picture than the
one on the real bin. Regenerating is one command, so this is a flag rather than
a decision baked into the scene.
"""
import os
import pathlib

import click
import cv2
import numpy as np
from cv2 import aruco

ASSETS = pathlib.Path(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))) / "assets"

DICTS = {
    "original": aruco.DICT_ARUCO_ORIGINAL,
    "4x4_50": aruco.DICT_4X4_50, "4x4_100": aruco.DICT_4X4_100,
    "4x4_250": aruco.DICT_4X4_250, "4x4_1000": aruco.DICT_4X4_1000,
    "5x5_50": aruco.DICT_5X5_50, "5x5_100": aruco.DICT_5X5_100,
    "5x5_250": aruco.DICT_5X5_250, "5x5_1000": aruco.DICT_5X5_1000,
    "6x6_50": aruco.DICT_6X6_50, "6x6_100": aruco.DICT_6X6_100,
    "6x6_250": aruco.DICT_6X6_250, "6x6_1000": aruco.DICT_6X6_1000,
    "7x7_50": aruco.DICT_7X7_50, "7x7_250": aruco.DICT_7X7_250,
}


@click.command()
@click.option("--dict", "dict_name", type=click.Choice(sorted(DICTS)),
              default="4x4_50", show_default=True)
@click.option("--ids", default="0,1,2,3")
@click.option("--px", default=480, type=int, help="Marker pixels (bit area).")
@click.option("--quiet-zone", default=0.15, type=float,
              help="White border as a fraction of marker side. ArUco needs one "
                   "to be detectable; a printed marker has the paper around it.")
def main(dict_name, ids, px, quiet_zone):
    ASSETS.mkdir(parents=True, exist_ok=True)
    d = aruco.getPredefinedDictionary(DICTS[dict_name])
    pad = int(round(px * quiet_zone))
    for i in (int(x) for x in ids.split(",")):
        img = aruco.generateImageMarker(d, i, px)
        canvas = np.full((px + 2 * pad, px + 2 * pad), 255, np.uint8)
        canvas[pad:pad + px, pad:pad + px] = img
        # 3-channel: MuJoCo skips a 1-channel PNG and the geom renders plain,
        # which looks like a blank sticker rather than an error.
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
        out = ASSETS / f"aruco_{dict_name}_{i}.png"
        cv2.imwrite(str(out), canvas)
        click.echo(f"  {out.name}  {canvas.shape[1]}x{canvas.shape[0]}px  "
                   f"(marker {px}px + {pad}px quiet zone)")
    (ASSETS / "aruco_meta.txt").write_text(
        f"dictionary={dict_name}\nids={ids}\nmarker_px={px}\n"
        f"quiet_zone_frac={quiet_zone}\nphysical_marker_mm=60\n")
    click.echo(f"\ndictionary: {dict_name}   -> {ASSETS}")


if __name__ == "__main__":
    main()
