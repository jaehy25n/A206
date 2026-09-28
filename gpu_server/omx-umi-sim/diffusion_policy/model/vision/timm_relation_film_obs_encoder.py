"""TimmObsEncoder + an ORACLE target/EE patch-relation FiLM on each frame's CLS (ablation B).

The single change: for every frame the ViT already processes, the patch tokens of
the SAME final-normalised token tensor the CLS comes from (tokens[:, 1:197]) are
pooled under the oracle target mask and the oracle fingertip mask, a relation
vector is built from the two pooled features and the masks' geometry, and a small
MLP turns it into a FiLM of that frame's CLS:

    CLS' = CLS * (1 + gamma) + beta

Everything after it -- temporal concat, low-dim concat, global_cond, UNet -- is
G0's. The last Linear of the MLP is zero-initialised (weight and bias), so at
step 0 gamma = beta = 0 and CLS' == CLS exactly. A frame whose target is not
usable (target_mask_valid false, or fewer than MIN_TARGET_PX target pixels after
the crop) is hard-gated: CLS' = CLS for that frame, independently per frame.

Geometry: the masks take exactly the crop the RGB takes. The encoder's transform
Sequential is walked module by module; RandomCrop draws its offset with its own
get_params (the same draw RandomCrop.forward makes), RGB and masks are cropped
with it, the RGB goes through the same Resize and ColorJitter modules, the masks
through a NEAREST resize and no jitter. RGB output and global RNG advancement are
therefore G0's (verified bit-exact). policy_server's CenterCrop swap is handled
the same way.

relation vector per frame (all computed after the crop, on 224 x 224):
    [f_T, f_E, f_T - f_E, f_T * f_E, dcx, dcy, log((area_T+1)/(area_E+1)), presence_T, presence_E]
    f_X = sum_i o_X[i] P[i] / (sum_i o_X[i] + eps), o_X = 16x16 area occupancy (ViT order)
    (cx, cy) = mask pixel centroid in [-1, 1]; an empty EE mask puts its centroid at 0
    presence_X = the mask has >= MIN_TARGET_PX pixels (presence_T is 1 whenever the branch is not gated)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision
import torchvision.transforms.functional as TF
from torchvision.transforms import InterpolationMode

from diffusion_policy.model.vision.timm_obs_encoder import TimmObsEncoder

PATCH = 16


class RelationFilm(nn.Module):
    def __init__(self, in_dim, hidden, out_dim):
        super().__init__()
        self.net = nn.Sequential(nn.LayerNorm(in_dim), nn.Linear(in_dim, hidden), nn.SiLU(),
                                 nn.Linear(hidden, 2 * out_dim))
        nn.init.zeros_(self.net[-1].weight)
        nn.init.zeros_(self.net[-1].bias)

    def forward(self, r):
        return self.net(r).chunk(2, dim=-1)


class TimmRelationFilmObsEncoder(TimmObsEncoder):
    def __init__(self, *args, target_mask_key="camera0_target_mask", ee_mask_key="camera0_ee_tip_mask",
                 target_valid_key="camera0_target_mask_valid", min_target_px=12, relation_hidden=256,
                 relation_init_seed=20260928, **kwargs):
        super().__init__(*args, **kwargs)
        assert self.model_name.startswith("vit") and self.feature_aggregation is None
        assert len(self.rgb_keys) == 1, "one camera"
        self.target_mask_key, self.ee_mask_key, self.target_valid_key = target_mask_key, ee_mask_key, target_valid_key
        self.min_target_px = int(min_target_px)
        self.relation_init_seed = int(relation_init_seed)
        dim = int(self.key_model_map[self.rgb_keys[0]].embed_dim)
        self.relation_in_dim = 4 * dim + 5
        with torch.random.fork_rng(devices=[]):
            torch.default_generator.manual_seed(self.relation_init_seed)   # CPU only: torch.manual_seed would also reseed CUDA
            self.relation_film = RelationFilm(self.relation_in_dim, int(relation_hidden), dim)
        self._twin_probe = None

    # ------------------------------------------------------------ geometry
    def _transform(self, key, img, masks):
        seq = self.key_transform_map[key]
        mods = list(seq) if isinstance(seq, nn.Sequential) else [seq]
        for t in mods:
            if isinstance(t, torchvision.transforms.RandomCrop):
                assert t.padding is None and not t.pad_if_needed
                i, j, h, w = t.get_params(img, t.size)
                img = TF.crop(img, i, j, h, w)
                if masks is not None:
                    masks = TF.crop(masks, i, j, h, w)
            elif isinstance(t, torchvision.transforms.CenterCrop):
                img = t(img)
                if masks is not None:
                    masks = t(masks)
            elif isinstance(t, torchvision.transforms.Resize):
                img = t(img)
                if masks is not None:
                    masks = TF.resize(masks, t.size, interpolation=InterpolationMode.NEAREST, antialias=False)
            elif isinstance(t, (torchvision.transforms.ColorJitter, nn.Identity)):
                img = t(img)
            else:
                raise RuntimeError(f"unhandled transform {type(t).__name__}")
        return img, masks

    # ------------------------------------------------------------ relation
    def _relation(self, cls, patches, masks, valid):
        mT, mE = masks[:, 0].float(), masks[:, 1].float()                    # [N, 224, 224]
        n, H, W = mT.shape
        occ = F.avg_pool2d(masks.float(), PATCH).flatten(2)                  # [N, 2, 196], row-major
        oT, oE = occ[:, 0], occ[:, 1]
        P = patches.float()
        fT = (oT.unsqueeze(-1) * P).sum(1) / (oT.sum(1, keepdim=True) + 1e-6)
        fE = (oE.unsqueeze(-1) * P).sum(1) / (oE.sum(1, keepdim=True) + 1e-6)
        aT, aE = mT.sum((1, 2)), mE.sum((1, 2))
        ys = (torch.arange(H, device=cls.device, dtype=torch.float32) + 0.5) / H * 2 - 1
        xs = (torch.arange(W, device=cls.device, dtype=torch.float32) + 0.5) / W * 2 - 1
        def centroid(m, a):
            cx = (m.sum(1) * xs).sum(1) / a.clamp(min=1)
            cy = (m.sum(2) * ys).sum(1) / a.clamp(min=1)
            return cx, cy
        cxT, cyT = centroid(mT, aT)
        cxE, cyE = centroid(mE, aE)
        presT = (aT >= self.min_target_px) & (valid > 0.5)
        presE = aE >= self.min_target_px
        r = torch.cat([fT, fE, fT - fE, fT * fE,
                       (cxT - cxE).unsqueeze(1), (cyT - cyE).unsqueeze(1),
                       torch.log((aT + 1) / (aE + 1)).unsqueeze(1),
                       presT.float().unsqueeze(1), presE.float().unsqueeze(1)], 1)
        gamma, beta = self.relation_film(r)
        mod = (cls * (1 + gamma) + beta).to(cls.dtype)
        out = torch.where(presT.unsqueeze(1), mod, cls)                     # hard fallback per frame
        if self._twin_probe is not None:
            self._twin_probe.record_film(cls, out, presT)
        return out

    def forward(self, obs_dict):
        features = list()
        batch_size = next(iter(obs_dict.values())).shape[0]
        for key in self.rgb_keys:
            img = obs_dict[key]
            B, T = img.shape[:2]
            assert B == batch_size
            assert img.shape[2:] == self.key_shape_map[key]
            img = img.reshape(B * T, *img.shape[2:])
            have = all(k in obs_dict for k in (self.target_mask_key, self.ee_mask_key, self.target_valid_key))
            masks = None
            if have:
                masks = torch.stack([obs_dict[self.target_mask_key], obs_dict[self.ee_mask_key]], 2)
                masks = masks.reshape(B * T, 2, *masks.shape[-2:])
            img, masks = self._transform(key, img, masks)
            tokens = self.key_model_map[key](img)                            # [B*T, 197, D], final norm
            feature = self.aggregate_feature(tokens)                         # tokens[:, 0] (CLS)
            if have:
                valid = obs_dict[self.target_valid_key].reshape(B * T).float()
                feature = self._relation(feature, tokens[:, 1:], masks, valid)
            assert len(feature.shape) == 2 and feature.shape[0] == B * T
            features.append(feature.reshape(B, -1))
        for key in self.low_dim_keys:
            data = obs_dict[key]
            B, T = data.shape[:2]
            assert B == batch_size
            assert data.shape[2:] == self.key_shape_map[key]
            features.append(data.reshape(B, -1))
        return torch.cat(features, dim=-1)
