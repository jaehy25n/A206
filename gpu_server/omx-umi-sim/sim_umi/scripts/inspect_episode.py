from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EPISODE = ROOT / "data" / "episode_0000.npz"
OUT = ROOT / "outputs"
OUT.mkdir(parents=True, exist_ok=True)

d = np.load(EPISODE)

rgb = d["rgb"]
timestamps = d["timestamps"]
tcp = d["tcp_pos"]
gripper = d["gripper_width"]
obj = d["object_pos"]

print("frames :", len(rgb))
print("duration:", timestamps[-1] - timestamps[0])
print("fps est :", (len(timestamps)-1) / (timestamps[-1]-timestamps[0]))
print()
print("object start:", obj[0])
print("object end  :", obj[-1])
print("gripper min/max:", gripper.min(), gripper.max())

# RGB -> OpenCV BGR
h, w = rgb.shape[1:3]

video_path = OUT / "episode_0000.mp4"

writer = cv2.VideoWriter(
    str(video_path),
    cv2.VideoWriter_fourcc(*"mp4v"),
    30.0,
    (w, h)
)

for frame in rgb:
    writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

writer.release()

# 몇 장 대표 이미지도 저장
indices = [
    0,
    len(rgb)//4,
    len(rgb)//2,
    3*len(rgb)//4,
    len(rgb)-1
]

for i in indices:
    cv2.imwrite(
        str(OUT / f"frame_{i:04d}.jpg"),
        cv2.cvtColor(rgb[i], cv2.COLOR_RGB2BGR)
    )

print()
print("video :", video_path)
print("frames:", [str(OUT / f'frame_{i:04d}.jpg') for i in indices])
