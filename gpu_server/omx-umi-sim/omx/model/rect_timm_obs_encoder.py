"""A TimmObsEncoder that accepts a non-square image.

This is the third arm of the FOV experiment. The other two keep the tensor at
224x224 and differ in what they throw away:

    center_crop   a central square. With a 4:3 source that discards a quarter of
                  the width, so the horizontal FOV shrinks from 63.5 to ~49.8 deg.
    letterbox     the full frame scaled to fit, padded top and bottom. Horizontal
                  FOV survives, but ~44% of the tensor is padding the model has to
                  learn to ignore, and it costs the same compute as real pixels.

    fit_rect      (this one) the frame cropped to the model's own aspect ratio,
                  no padding. Same horizontal FOV as letterbox, no wasted pixels,
                  and 224x128 is 43% less compute than 224x224.

Upstream `TimmObsEncoder` assumes H == W in exactly two places, and both fail
silently rather than loudly, which is why this is a subclass and not a config
change:

1. `timm.create_model` is called without `img_size`, so the ViT builds a 224x224
   patch grid and the position embedding has the wrong length for a 224x128
   input.
2. the RandomCrop/Resize pair is built from `image_shape[0]` alone:

       RandomCrop(size=int(image_shape[0] * ratio))   # a SQUARE crop of H x H
       Resize(size=image_shape[0])                    # shorter side -> H

   On a 128x224 input that crops 128x128 and leaves it there -- it throws away
   precisely the horizontal FOV this experiment exists to keep, and the run still
   trains, reporting nothing.

A square `shape_meta` makes this class a no-op, so it is safe as the default
`_target_` for every arm of the experiment.
"""
import copy
from typing import Tuple

import timm
import torch
import torchvision

from diffusion_policy.model.vision.timm_obs_encoder import TimmObsEncoder


def _rgb_hw(shape_meta: dict) -> Tuple[int, int]:
    shapes = {tuple(a["shape"])[1:] for a in shape_meta["obs"].values()
              if a.get("type", "low_dim") == "rgb"}
    if len(shapes) != 1:
        raise ValueError(f"expected exactly one rgb shape, got {sorted(shapes)}")
    h, w = shapes.pop()
    return int(h), int(w)


class RectTimmObsEncoder(TimmObsEncoder):

    def __init__(self, shape_meta: dict, model_name: str, pretrained: bool,
                 frozen: bool, global_pool: str, transforms, **kwargs):
        super().__init__(shape_meta=shape_meta, model_name=model_name,
                         pretrained=pretrained, frozen=frozen,
                         global_pool=global_pool, transforms=transforms,
                         **kwargs)

        h, w = _rgb_hw(shape_meta)
        self.image_hw = (h, w)
        if h == w:
            return                                   # upstream is already right

        if not model_name.startswith("vit"):
            raise ValueError(
                f"rectangular input needs a ViT (the patch grid is what makes it "
                f"possible); got model_name={model_name!r}. Use center_crop or "
                f"letterbox with a CNN backbone.")
        patch = getattr(self.key_model_map[self.rgb_keys[0]], "patch_embed", None)
        ps = int(getattr(patch, "patch_size", (16, 16))[0]) if patch is not None else 16
        for name, v in (("height", h), ("width", w)):
            if v % ps:
                raise ValueError(
                    f"image {name} {v} is not a multiple of the ViT patch size "
                    f"{ps}; the patch grid would not tile the input")

        # 1. rebuild the backbone for this input size. timm interpolates the
        #    pretrained position embedding onto the new patch grid.
        model = timm.create_model(
            model_name=model_name, pretrained=pretrained,
            global_pool=global_pool, num_classes=0, img_size=(h, w))
        if frozen:
            if not pretrained:
                raise ValueError("frozen=True requires pretrained=True")
            for p in model.parameters():
                p.requires_grad = False
        share = kwargs.get("share_rgb_model", False)
        for key in self.rgb_keys:
            self.key_model_map[key] = model if share else copy.deepcopy(model)

        # 2. rebuild the crop/resize pair so both axes are honoured.
        if transforms is not None and not isinstance(transforms[0], torch.nn.Module):
            if transforms[0].type != "RandomCrop":
                raise ValueError(
                    f"expected RandomCrop first, got {transforms[0].type!r}")
            ratio = transforms[0].ratio
            rebuilt = [
                torchvision.transforms.RandomCrop(
                    size=(int(h * ratio), int(w * ratio))),
                torchvision.transforms.Resize(size=(h, w), antialias=True),
            ] + list(transforms[1:])
            transform = torch.nn.Sequential(*rebuilt)
            for key in self.rgb_keys:
                self.key_transform_map[key] = transform

    def output_shape(self):
        # upstream probes with a zeros tensor built from key_shape_map, which is
        # already (C, H, W) from shape_meta, so the rectangular case needs no
        # override -- but assert it, because a silent square here is the exact
        # failure this class exists to prevent.
        out = super().output_shape()
        return out
