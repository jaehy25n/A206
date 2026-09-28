"""G0 + a train-only, phase-masked time-to-event auxiliary regression (ablation A).

The single change to DiffusionUnetTimmPolicy: a small head reads the diffusion
model's own observation condition g [B, 1568] (both frames' CLS + low-dim) and
regresses the normalised time to the next manipulation event. Its loss reaches
the obs encoder (ViT) through g; it is not connected to the UNet, which is
trained by the diffusion loss only. predict_action is inherited unchanged: the
head is never evaluated at inference.

Supervision uses the labels of the CURRENT observation row r only:
    phase APPROACH    -> time_to_close   (output 0)
    phase GRASP_LIFT  -> time_to_lift    (output 1)
    phase TRANSPORT   -> time_to_open    (output 2)
    RELEASE, RETREAT_POST -> nothing
    y_e = clip(dt_e / T_e, 0, 1),  T_e = P95 of dt_e over that phase's training samples
    L_e = SmoothL1 over the samples of that phase in the batch (skipped when none)
    L_aux = mean of the active L_e;  L_total = L_diff + aux_weight * L_aux
The phase is a loss mask only, never an input.
"""
from typing import Dict, Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F
from einops import reduce

from diffusion_policy.policy.diffusion_unet_timm_policy import DiffusionUnetTimmPolicy

EVENTS = ("close", "lift", "open")


class DiffusionUnetTimmTimingAuxPolicy(DiffusionUnetTimmPolicy):
    new_module_prefixes = ("timing_head.",)

    def __init__(self, *args, timing_scales_s: Sequence[float], aux_weight: float = 0.1,
                 smooth_l1_beta: float = 1.0, aux_hidden: int = 256, aux_init_seed: int = 20260928,
                 **kwargs):
        super().__init__(*args, **kwargs)
        assert len(timing_scales_s) == 3 and all(float(x) > 0 for x in timing_scales_s)
        self.timing_scales_s = [float(x) for x in timing_scales_s]
        self.aux_weight = float(aux_weight)
        self.smooth_l1_beta = float(smooth_l1_beta)
        self.aux_init_seed = int(aux_init_seed)
        d = int(self.obs_feature_dim)
        # built in a forked RNG so that the global stream -- and with it the
        # sample order, crops, jitter and diffusion noise -- is G0's
        with torch.random.fork_rng(devices=[]):
            torch.default_generator.manual_seed(self.aux_init_seed)   # CPU only: torch.manual_seed would also reseed CUDA
            self.timing_head = nn.Sequential(
                nn.LayerNorm(d), nn.Linear(d, aux_hidden), nn.SiLU(), nn.Linear(aux_hidden, 3))
        self.last_loss_terms = None

    def new_module_parameters(self):
        return self.timing_head.parameters()

    def aux_provenance(self):
        return {"ablation": "timing_aux", "timing_scales_s": dict(zip(EVENTS, self.timing_scales_s)),
                "aux_weight": self.aux_weight, "smooth_l1_beta": self.smooth_l1_beta,
                "aux_init_seed": self.aux_init_seed, "head_input": "global_cond g (obs condition of the UNet)",
                "phase_to_event": {"APPROACH": "close", "GRASP_LIFT": "lift", "TRANSPORT": "open"}}

    def compute_loss(self, batch):
        # ---- identical to DiffusionUnetTimmPolicy.compute_loss (same ops, same RNG draws, same order)
        assert 'valid_mask' not in batch
        nobs = self.normalizer.normalize(batch['obs'])
        nactions = self.normalizer['action'].normalize(batch['action'])

        assert self.obs_as_global_cond
        global_cond = self.obs_encoder(nobs)
        g = global_cond

        if self.train_diffusion_n_samples != 1:
            global_cond = torch.repeat_interleave(global_cond,
                repeats=self.train_diffusion_n_samples, dim=0)
            nactions = torch.repeat_interleave(nactions,
                repeats=self.train_diffusion_n_samples, dim=0)

        trajectory = nactions
        noise = torch.randn(trajectory.shape, device=trajectory.device)
        noise_new = noise + self.input_pertub * torch.randn(trajectory.shape, device=trajectory.device)
        timesteps = torch.randint(
            0, self.noise_scheduler.config.num_train_timesteps,
            (nactions.shape[0],), device=trajectory.device
        ).long()
        noisy_trajectory = self.noise_scheduler.add_noise(
            trajectory, noise_new, timesteps)
        pred = self.model(
            noisy_trajectory,
            timesteps,
            local_cond=None,
            global_cond=global_cond
        )
        pred_type = self.noise_scheduler.config.prediction_type
        if pred_type == 'epsilon':
            target = noise
        elif pred_type == 'sample':
            target = trajectory
        else:
            raise ValueError(f"Unsupported prediction type {pred_type}")
        loss = F.mse_loss(pred, target, reduction='none')
        loss = loss.type(loss.dtype)
        loss = reduce(loss, 'b ... -> b (...)', 'mean')
        loss_diff = loss.mean()

        # ---- the one addition: phase-masked timing regression on g (no RNG)
        tau = self.timing_head(g).float()                                   # [B, 3]
        phase = batch['aux']['phase'].long()
        dt = batch['aux']['dt'].float()
        scales = torch.tensor(self.timing_scales_s, device=tau.device, dtype=torch.float32)
        y = (dt / scales).clamp(0.0, 1.0)
        active, terms = [], {}
        for e, name in enumerate(EVENTS):
            m = phase == e
            n = int(m.sum())
            terms[f"{name}_valid_count"] = n
            if n == 0:
                terms[f"{name}_mae_seconds"] = float('nan')
                continue
            active.append(F.smooth_l1_loss(tau[m, e], y[m, e], beta=self.smooth_l1_beta))
            terms[f"{name}_mae_seconds"] = float(((tau[m, e] - y[m, e]).abs() * scales[e]).mean().detach())
        loss_aux = torch.stack(active).mean() if active else torch.zeros((), device=tau.device)
        loss_total = loss_diff + self.aux_weight * loss_aux
        terms.update(loss_total=float(loss_total.detach()), loss_diff=float(loss_diff.detach()),
                     loss_aux=float(loss_aux.detach()),
                     loss_aux_weighted=float(self.aux_weight * loss_aux.detach()))
        self.last_loss_terms = terms
        return loss_total
