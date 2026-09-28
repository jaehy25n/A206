"""ORACLE target / end-effector masks: geometry helpers shared by the sidecar
builder, its validation and (later) a training loader.

Oracle = rendered from the simulator's ground truth (MuJoCo segmentation of the
same model the plant runs), not estimated. Never a policy input at deployment.

G0 geometry (the policy's image path, demos_to_umi_zarr.center_crop_resize):
    raw 320x180 -> central 180x180 (x 70..250) -> 224x224
RGB uses INTER_AREA; a mask takes the same crop and INTER_NEAREST, so a mask
stays binary. Train-time augmentation (TimmObsEncoder, torchvision 0.16):
    RandomCrop(212) -> Resize(224, bilinear, antialias) -> ColorJitter
one crop offset per forward call, shared by every image of the batch (B*T).
A mask has to take exactly that (top, left) and a NEAREST resize, and no
ColorJitter -- crop_resize_pair() below is that operation, in torch.
ViT-B/16 then cuts the 224x224 input into 14x14 patches of 16x16 px, row-major
(patch_embed conv stride 16 -> flatten), which patch_occupancy() follows.
"""
import numpy as np

RAW_WH = (320, 180)
G0_SIDE = 180
G0_X0 = (RAW_WH[0] - G0_SIDE) // 2
G0_OUT = 224
TRAIN_CROP = int(G0_OUT * 0.95)          # 212, as TimmObsEncoder builds it
PATCH = 16
GRID = G0_OUT // PATCH                   # 14


def g0_mask(mask_raw):
    """[180, 320] bool -> [224, 224] bool, the G0 crop with nearest resize."""
    import cv2
    m = np.ascontiguousarray(mask_raw[:, G0_X0:G0_X0 + G0_SIDE]).astype(np.uint8)
    return cv2.resize(m, (G0_OUT, G0_OUT), interpolation=cv2.INTER_NEAREST).astype(bool)


def patch_occupancy(mask224):
    """[..., 224, 224] mask -> [..., 196] fraction of each 16x16 patch covered, in
    ViT token order (row-major over the 14x14 grid). Area, not centre point."""
    m = np.asarray(mask224, dtype=np.float32)
    lead = m.shape[:-2]
    m = m.reshape(*lead, GRID, PATCH, GRID, PATCH)
    return m.mean(axis=(-3, -1)).reshape(*lead, GRID * GRID)


def eval_crop_offset():
    """(top, left) of the deterministic evaluation CenterCrop(212) on 224 (torchvision rounding)."""
    o = int(round((G0_OUT - TRAIN_CROP) / 2.0))
    return o, o


def crop_resize_pair(rgb, masks, top, left, size=TRAIN_CROP, out=G0_OUT):
    """The augmentation's geometry applied to RGB and masks with ONE offset.

    rgb   float tensor [N, 3, 224, 224]  -> crop, bilinear antialiased resize
    masks tensor [N, K, 224, 224] (0/1)   -> the same crop, NEAREST resize
    ColorJitter is for the caller to apply to the RGB only, after this.
    """
    import torch
    import torchvision.transforms.functional as F
    from torchvision.transforms import InterpolationMode
    r = F.resized_crop(rgb, top, left, size, size, [out, out], antialias=True)
    m = F.resized_crop(masks.to(torch.uint8), top, left, size, size, [out, out],
                       interpolation=InterpolationMode.NEAREST)
    return r, m
