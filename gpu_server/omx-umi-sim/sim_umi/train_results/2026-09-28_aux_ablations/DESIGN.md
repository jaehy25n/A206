# Two single-change ablations on G0: design (no code written yet)

- **A (GPU 0):** G0 + a train-only, phase-masked time-to-close / lift / open auxiliary
  regression.
- **B (GPU 5):** G0 + a FiLM driven by the relation between the ORACLE target and EE
  patches.

Each run adds exactly one thing to the definitive G0 recipe. Everything else is held fixed
and is checked, not assumed (section 4).

## 0. What G0 is (read from the code)

- **Observation.** `camera0_rgb`, T = 2 frames (rows r−1 and r), goes through the G0 image
  path and then the encoder transform:
  - train: RandomCrop 212 → Resize 224 (bilinear, antialias) → ColorJitter;
  - eval: CenterCrop 212 → Resize.
  - The transform lives in `TimmObsEncoder.forward`. One crop offset and one set of jitter
    parameters are drawn per call and shared by all B·T images.
- **Backbone.** CLIP ViT-B/16 (`vit_base_patch16_clip_224.openai`, timm 0.9.7). Its output
  is (B·T, 197, 768): index 0 is CLS and 1..196 are the patch tokens (row-major 14×14),
  after the final LayerNorm. For a ViT the encoder **keeps only CLS** (`aggregate_feature`
  returns `feature[:, 0]`); `attention_pool_2d` in the config is ignored. The patch tokens
  are computed and then discarded today.
- **Diffusion condition.** `global_cond` = [CLS_{r−1}, CLS_r, low-dim ×2] with D = 1536 + 32
  = 1568. It feeds `ConditionalUnet1D`, which already FiLMs its blocks on `global_cond`.
  Action: 16 × 10.
- **Loss.** L_diff = MSE on the noise (ε-prediction). In G0 it runs 1.06 at step 0, 0.046
  at 1k, 0.020 at 3k and 0.0125 at 11.4k.
- **Recipe.**
  - `.hydra` of `2026-09-27_amp_v2_definitive`: seed 42, init from `shared_init/init_state.pt`
    (strict), val_ratio 0.0, batch 64, 8 workers.
  - AdamW 3e-4: UNet group at 3e-4 and obs-encoder group at 3e-5 (pretrained ×0.1),
    weight decay 1e-6.
  - Cosine schedule, warmup 2000, total 11400; fp16 AMP; EMA; 11400 optimizer steps,
    about 80 min on a V100.
- **Randomness.** No `dataloader_seed` is set. The shuffle order, the worker seeds, the crop
  and the jitter all come from the global torch RNG after model construction and the
  init load.

## 1. Experiment A: phase-masked time-to-event auxiliary regression

```
 obs (2 frames) ──► TimmObsEncoder (unchanged) ──► global_cond g  [B, 1568]
                                                        │
                        ┌───────────────────────────────┤
                        ▼                               ▼
              ConditionalUnet1D (unchanged)      aux head h(g)  [NEW, train-only]
                        │                        Linear 1568→256, Mish, Linear 256→3
                        ▼                               │
                 L_diff (unchanged)          ŷ = (ŷ_close, ŷ_lift, ŷ_open)
                        │                               │   targets y_e, masks m_e
                        └──────────► L = L_diff + λ · L_aux ◄──┘
```

**Input.** The head reads the diffusion model's own condition `g`, which is the "policy
latent". Its gradient reaches the ViT, the only learned part of `g`, so the visual
representation is what gets pushed to carry timing. No new input exists at inference.

**Targets.** The values are taken from the labels sidecar at the sample's current row r.
- y_e = min(dt_to_e, T_cap) / T_cap, with T_cap = 3.2 s (two action horizons).
- Inside the cap: close 26 %, lift 23 %, open 11 % of the masked training samples (open is
  low because TRANSPORT is long). The rest carry "far" = 1.
- The sidecar keeps the raw dt. The clip and scale happen in the loss, from config.

**Phase mask.** m_e = e_is_future at row r, which is the same as supervising e only in the
phases before its boundary:

| event | supervised in | share of samples |
|---|---|---|
| close | APPROACH | 36.3 % |
| lift | APPROACH + GRASP_LIFT | 41.9 % |
| open | APPROACH .. TRANSPORT | 85.2 % |

After its event, a head gets no gradient at all. It is not taught a fake 0.

**Loss.**
- L_aux = mean over e of [ Σ_b m_e · SmoothL1(ŷ_e, y_e) / max(1, Σ_b m_e) ], in fp32.
- **λ = 0.1**, constant. The aux loss starts around 0.1 (so λ·L_aux ≈ 0.01, about 1 % of
  L_diff = 1.06) and falls to about 0.01–0.02. Late in training λ·L_aux is then roughly
  0.001–0.002 against L_diff = 0.0125, i.e. 10–15 %.
- There is no schedule. Changing λ would be a second experiment.

**Inference.** `predict_action` is unchanged, and the head is never evaluated. The
checkpoint carries the head, which policy_server simply ignores.

**Logged.** L_diff and L_aux are logged separately. `train_loss` stays L_diff, so it
compares with G0. Per-event MAE inside the cap is logged too, on train, and offline on
val_v2 (held-out demos).

## 2. Experiment B: oracle target–EE patch relation FiLM

```
 rgb [B,T,3,224,224]  target_mask, ee_tip_mask [B,T,224,224]  target_valid [B,T]
        │                       │
        └── ONE crop offset (RandomCrop.get_params) ─► crop_resize_pair: rgb bilinear,
                                                        masks NEAREST; ColorJitter on rgb only
        ▼                                    ▼
   ViT-B/16 (unchanged) ─► tokens [B·T,197,768]      occupancy o_T, o_E [B·T,196] (area, after crop)
        │         │                                   │
        │   CLS   │ patches P [196,768]               │
        │         └──► f_T = Σ o_T P / Σ o_T ,  f_E = Σ o_E P / Σ o_E           (pooled, no new ViT pass)
        │              geo = [c_T − c_E (2), log area_T, log area_E, π_T, π_E]   (from the masks)
        │              r = MLP([LN f_T·π_T, LN f_E·π_E, (f_T − f_E)·π_T, geo])  768·3+6 → 256 → 256
        │              (γ, β) = Linear 256 → 2·768, ZERO-initialised              [NEW]
        ▼
   CLS' = CLS ⊙ (1 + γ) + β        per frame                                      [NEW]
        │
   global_cond = [CLS'_{r−1}, CLS'_r, low-dim]  ─► ConditionalUnet1D (unchanged) ─► L_diff (unchanged)
```

- **What is added.** One relation-conditioned FiLM on each frame's CLS feature. The relation
  is computed from the same ViT forward, by pooling the patch tokens under the oracle
  masks. Nothing is added to the loss: L = L_diff.
- **Patch weights.** `oracle_masks.patch_occupancy` is applied **after** the shared crop and
  resize. It uses area fractions in ViT token order, not centre points.
- **EE mask: `ee_tip_mask`** (recommended). In a wrist camera the fingers barely move in the
  image; only the jaw changes. So the useful relation is where the target sits and how big
  it is relative to the fingertips, plus what the tokens look like where the two meet. The
  gripper mask would add the static finger body. The alternative is not run.
- **Presence flags.**
  - π_T = 1 when `target_mask_valid` holds and the target covers at least 12 px after the
    crop.
  - When π_T = 0, f_T is set to 0 and c_T to c_E. This covers not visible, outside the crop,
    and the 606 release-to-rest rows.
  - So the release-to-rest rows never feed a target relation, as agreed.
- **Identity at initialisation.** With γ = β = 0, step 0 is G0 exactly. The FiLM learns only
  as far as the diffusion loss finds it useful.
- **Inference.** The masks must arrive with each observation, under the same eval geometry:
  CenterCrop offset (6, 6), nearest resize. The model side is simple: the masks are obs
  keys with identity normalisers.
- **Needs a decision.** The closed-loop evaluator has to supply oracle masks per
  observation. That is an evaluator-side addition (section 5, item 4) and it is not part of
  the training change. Training and offline checks do not need it.

## 3. Code changes needed for each run (none made yet)

| place | A | B |
|---|---|---|
| dataset (UmiDataset subclass, flag in the task yaml) | Reads the labels sidecar by row. Returns `batch['aux'] = {dt[3], is_future[3]}` at the current row. Nothing is added to `obs`. | Reads the mask sidecar by row. Slices it with the RGB rule {r−1, r} plus first-frame padding. Returns `obs['camera0_target_mask']`, `obs['camera0_ee_tip_mask']` (uint8) and `obs['camera0_target_valid']`. `get_normalizer` gives these keys identity. |
| encoder | unchanged | Returns the patch tokens beside CLS. When masks are present, the Sequential call is replaced by explicit `get_params` + `crop_resize_pair` + ColorJitter (verified: same image, same RNG state). Relation MLP + FiLM. |
| policy | `compute_loss` adds λ·L_aux (reads `batch['aux']`). `predict_action` unchanged. | Unchanged, apart from routing the mask keys to the encoder. |
| workspace | New modules are built under `torch.random.fork_rng` with their own seed, so the global RNG after construction equals G0's. The shared init is loaded strict on G0's keys, and the only missing keys must be the new module's. A third optimizer group holds the new modules (lr 3e-4, same weight decay, same cosine schedule); groups 1–2 are untouched. EMA covers everything. Both loss terms are logged. | Same. |
| config | A copy of the omx workspace/task yaml with the one change. Overrides are identical to the definitive run: seed 42, the same init_state, val_ratio 0.0, 11400 steps, fp16, the same checkpoint steps. | Same. |

## 4. Invariance gates before any full run

These are checked with a short twin harness: the G0 code path and the A or B code path, the
same seed and the same init, about 20 optimizer steps each.

1. **Same randomness.** The sampled row indices per batch, the crop offsets, the jitter
   parameters, the diffusion noise and the timesteps are identical to G0's.
   - A's head consumes no RNG. B's explicit crop path consumes exactly what the Sequential
     did (verified).
   - New modules are built in a forked RNG.
2. **Same start.** At step 0 the parameters that also exist in G0 have G0's init checksum.
   - A: step-0 L_diff equals G0's bitwise.
   - B: step-0 `global_cond` and L_diff equal G0's bitwise, because the FiLM is zero.
3. **Fixed recipe.** The dataset, rows, geometry, augmentation, backbone, diffusion, action
   dimension, schedule and step count are identical. This is compared through the resolved
   config diff against G0 and should differ only in the added module, loss term and data
   keys.
4. **Masks follow the crop (B only).** For the batches of the twin run, the cropped masks
   from inside the encoder, overlaid on the cropped RGB, match the sidecar alignment.
5. **Scheduling.** A trains on GPU 0 and B on GPU 5, at the same time, with 8 CPU workers
   each. No rollout, render or simulator diagnostic runs during training. The idle DSE
   bringup stays on GPU 0 (244 MiB) and is not used.

## 5. Decision points

1. **A, λ = 0.1 and T_cap = 3.2 s.** The alternatives would be separate runs.
2. **A's head reads g.** The alternative is the two CLS features only (visual-only).
3. **B uses `ee_tip_mask`.** The alternative is `ee_gripper_mask`.
4. **B's closed-loop evaluation needs oracle masks per observation.** The recommended source
   in the timing-controlled evaluator:
   - arm and jaw from the paired joint snapshot, which is already exact at the capture tick;
   - the ball from the same pre_step snapshot, by adding the object's free-joint pose to the
     existing snapshot message in the camera plugin (one small extension of the plugin
     already patched);
   - render the masks with the same `build_oracle_masks` code in the bridge.
   Without a plugin change, the latest 20 Hz free-joint message would reintroduce the
   0–50 ms ball lag at evaluation. Either way this touches the evaluator, which is your
   call.
5. **Evaluation after training.** EMA at step 11400 on the frozen canonical condition
   (0.6 s timing-controlled nominal 5, ×2), against G0 (lifted 8/10, bin 2/10). A can go
   first; B waits on item 4.
