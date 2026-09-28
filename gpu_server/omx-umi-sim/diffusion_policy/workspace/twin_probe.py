"""Twin-gate probe: records, per training step, everything that must be identical
between the G0 code path and an ablation's code path given the same seed/init.

Records only; draws no randomness. Enabled by training.twin_probe_path.
  - global CPU / CUDA RNG state (sha) at the start of each step
  - the sample indices of the batch (dataset.emit_sample_index)
  - every RandomCrop / ColorJitter parameter draw (wrapped get_params, same draws)
  - what the UNet receives: timesteps (exact), noisy trajectory and global_cond (sha)
  - the diffusion loss before backward (float + exact bits)
  - step 0: global_cond saved to disk; for the relation FiLM max |CLS' - CLS|
"""
import hashlib
import json
import pathlib
import struct

import torch
import torchvision


def _sha(t):
    return hashlib.sha256(t.detach().to("cpu").contiguous().numpy().tobytes()).hexdigest()[:20]


class TwinProbe:
    def __init__(self, path, n_steps, policy):
        self.path = pathlib.Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.n = int(n_steps)
        self.rows, self.cur, self.step = [], None, 0
        self._orig_crop = torchvision.transforms.RandomCrop.get_params
        self._orig_jit = torchvision.transforms.ColorJitter.get_params
        probe = self

        def crop_params(img, output_size):
            out = probe._orig_crop(img, output_size)
            if probe.cur is not None:
                probe.cur["crop"].append([int(x) for x in out])
            return out

        def jit_params(brightness, contrast, saturation, hue):
            out = probe._orig_jit(brightness, contrast, saturation, hue)
            if probe.cur is not None:
                fn_idx, b, c, s, h = out
                probe.cur["jitter"].append({"order": [int(x) for x in fn_idx],
                                            "b": None if b is None else float(b), "c": None if c is None else float(c),
                                            "s": None if s is None else float(s), "h": None if h is None else float(h)})
            return out
        torchvision.transforms.RandomCrop.get_params = staticmethod(crop_params)
        torchvision.transforms.ColorJitter.get_params = staticmethod(jit_params)

        def unet_pre(mod, args, kwargs):
            if probe.cur is None or "unet_calls" not in probe.cur:
                return
            x, t = args[0], args[1]
            gc = kwargs.get("global_cond")
            probe.cur["unet_calls"].append({"timesteps": [int(v) for v in t.flatten().tolist()],
                                            "noisy_sha": _sha(x.float()), "global_cond_sha": _sha(gc.float())})
            if probe.step == 0 and not (probe.path / "global_cond_step0.pt").exists():
                torch.save(gc.detach().float().cpu(), probe.path / "global_cond_step0.pt")
        self._h = policy.model.register_forward_pre_hook(unet_pre, with_kwargs=True)
        enc = policy.obs_encoder
        if hasattr(enc, "_twin_probe"):
            enc._twin_probe = self

    def record_film(self, cls, out, gate):
        if self.cur is not None:
            self.cur.setdefault("film", []).append({
                "max_abs_cls_mod_minus_cls": float((out.float() - cls.float()).abs().max()),
                "frames": int(cls.shape[0]), "frames_active": int(gate.sum())})

    def begin(self, global_step, batch):
        if self.step >= self.n:
            self.cur = None
            return
        self.cur = {"step": self.step, "global_step": int(global_step),
                    "rng_cpu_sha": hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest()[:20],
                    "rng_cuda_sha": hashlib.sha256(torch.cuda.get_rng_state().numpy().tobytes()).hexdigest()[:20],
                    "sample_idx": [int(v) for v in batch["_sample_idx"].tolist()],
                    "crop": [], "jitter": [], "unet_calls": []}

    def after_forward(self, loss_diff):
        if self.cur is None:
            return
        v = float(loss_diff)
        self.cur["loss_diff"] = v
        self.cur["loss_diff_bits"] = struct.pack(">f", v).hex()

    def end(self, opt_steps, skipped, lrs):
        if self.cur is None:
            return
        self.cur.update(opt_steps=int(opt_steps), skipped=bool(skipped), lrs=[float(x) for x in lrs])
        self.rows.append(self.cur)
        self.cur = None
        self.step += 1
        (self.path / "twin_probe.json").write_text(json.dumps(self.rows, indent=1))

    def close(self):
        torchvision.transforms.RandomCrop.get_params = staticmethod(self._orig_crop)
        torchvision.transforms.ColorJitter.get_params = staticmethod(self._orig_jit)
        self._h.remove()
