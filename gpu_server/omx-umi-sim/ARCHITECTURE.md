# Architecture

The system has two halves. Most of the work in this tree is the second.

1. **Real-data path** (first phase). Phone-recorded sessions are processed on a CPU
   server, mirrored to a GPU server, built into a UMI zarr and trained there. The
   policy is then handed off for inference on a Jetson.
2. **Simulation path.** A MuJoCo + ROS 2 twin of the OMX cell covers a scripted
   expert, demonstrations, training, and closed-loop evaluation under controlled
   timing.

## 1. Real-data path (omx/, README_GPU_WORKFLOW.md, README_CPU_GPU_SYNC.md, jetson_handoff/)

```mermaid
flowchart LR
  S10[Galaxy S10 capture] --> API[FastAPI ingest] --> CPU[CPU preprocessing<br/>processed/v1 + READY]
  CPU -- rsync over SSH, GPU pulls --> MIR[GPU mirror]
  MIR --> ZARR[omx.data.build<br/>processed_v1 -> UMI zarr]
  ZARR --> TRAIN[train.py<br/>UMI Diffusion Policy]
  TRAIN --> CKPT[checkpoint]
  CKPT --> JET[Jetson inference<br/>jetson_handoff/]
  JET --> ROBOT[OMX execution layer<br/>16 x 10 relative EE trajectory -> 5-DoF]
```

## 2. The simulated cell

```mermaid
flowchart TB
  subgraph PLANT["MuJoCo plant: ros2_control_node (mujoco_ros2_control 0.1.2 + patched camera plugin)"]
    MJ[collector_scene.xml<br/>OMX 5-DoF arm, pivot gripper, wrist camera 320x180 fovy 39.8,<br/>50 mm ball, bin, desk]
    CAM[camera plugin<br/>trigger sim_state: capture every 25 physics steps of 2 ms<br/>+ joint snapshot of the same mjData, same stamp<br/>+ optional free-joint poses object/bin]
    FJ[free-joint state publisher 20 Hz<br/>verification only]
    JTC[arm_controller: JointTrajectoryController]
    GRIP[gripper_controller]
    MJ --- CAM
    MJ --- FJ
    JTC --> MJ
    GRIP --> MJ
  end
  MOVEIT[MoveIt move_group<br/>planning scene: table, paper, bin] -.scripted expert only.-> JTC
```

- **Wrist camera.** Position, pitch and fovy were matched to recordings from the real
  collector (`sim_umi/reference/`, `sim_umi/PROJECT_STATUS.md`).
- **Magenta fingertip patches.** They exist only so the gripper width can be read from
  the image (`gripper_vision.py`). They are painted out before the policy sees the
  frame.

## 3. Data: scripted expert -> demos -> zarr

```mermaid
flowchart LR
  EXP[collect_demos.py<br/>scripted expert, 10 stages:<br/>HOME SEARCH_OBJECT APPROACH_OBJECT GRASP LIFT<br/>SEARCH_BIN TRANSPORT PLACE RETREAT SETTLE] --> NPZ[demos/*/episode_*.npz @10 Hz<br/>RGB, TCP pose at the image instant, camera-estimated width,<br/>+ GT metadata: jaw width, ball pose, stage, visibility]
  NPZ --> Z[demos_to_umi_zarr.py<br/>cut where dt > 0.105 s, keep pieces >= 17 frames,<br/>G0 center crop 180x180 -> 224, JPEG-XL]
  Z --> ZA[omx_sim_train.zarr.zip<br/>clean: 20 demos]
  Z --> ZB[omx_sim_train_v2.zarr.zip<br/>clean + corrective v2: 68 demos -> 94 episodes, 22 942 rows]
  NPZ --> SC[labels + oracle masks sidecars<br/>build_label_sidecar.py / build_oracle_masks.py]
```

- **Policy inputs.** Wrist RGB, relative EE pose (pos + rot6d), rotation relative to
  the start, and the camera-estimated gripper width. Ground truth is recorded but is
  never a policy input.
- **Sidecars.** The label and oracle-mask sidecars are row-aligned with the zarr. They
  never modify it. See `sim_umi/train_results/2026-09-27_aux_prep/PREP_REPORT.md`.

## 4. The policy

```mermaid
flowchart LR
  RGB["camera0_rgb x2 frames (r-1, r)"] --> AUG["train: RandomCrop 212 -> Resize 224 -> ColorJitter<br/>eval: CenterCrop 212 -> Resize 224"]
  AUG --> VIT["CLIP ViT-B/16<br/>vit_base_patch16_clip_224.openai<br/>tokens [197, 768] after final LN"]
  VIT -- "CLS (token 0)" --> CAT
  LOW["low-dim x2: eef pos, rot6d, rot wrt start, gripper width"] --> CAT["global_cond g [1568]"]
  CAT --> UNET["ConditionalUnet1D (FiLM on g)<br/>DDIM, 16 inference steps"]
  UNET --> ACT["action 16 x 10<br/>rel pos 3 + rot6d 6 + width 1"]
  VIT -. "B: patches [196, 768] pooled by oracle target / tip masks<br/>-> relation MLP -> zero-init FiLM of CLS" .-> CAT
  CAT -. "A: train-only head g -> LN -> 256 -> SiLU -> 3<br/>phase-masked time-to-close/lift/open" .-> AUX[L_aux]
```

- **Training.** AdamW at 3e-4, with the encoder at 3e-5. Cosine schedule with 2000
  warmup steps. 11 400 successful updates, batch 64, fp16 AMP, EMA, seed 42, and a
  shared initial state `a4cd264f` for every variant.
- **Configs.** They are in `diffusion_policy/config/train_diffusion_unet_timm_omx_*`:
  `_workspace` (G0), `_rect_` (G2), `_timing_aux_` (A) and
  `_oracle_tip_relation_film_` (B).
- **Ablation A.** The auxiliary head reads the diffusion condition `g`. Supervision is
  phase-masked: APPROACH trains close, GRASP_LIFT trains lift, TRANSPORT trains open.
  L = L_diff + 0.1 x masked SmoothL1. `predict_action` is unchanged.
- **Ablation B.** Patch tokens come from the same final-normalised tensor as CLS. They
  are pooled by area occupancy under the post-crop oracle masks. The relation vector is
  [f_T, f_E, f_T-f_E, f_T*f_E, dcx, dcy, log area ratio, presences]. It drives
  CLS' = CLS * (1 + gamma) + beta with a zero-initialised last layer, so step 0 is G0
  exactly. Frames whose target is missing or invalid fall back hard to CLS.
- **Controlled comparisons.** New modules are built in a forked CPU RNG, so batch order,
  crops, jitter and diffusion noise stay identical to G0's. This is proven by a twin
  gate (`sim_umi/scripts/aux/`).

## 5. Closed loop and the two evaluators

```mermaid
sequenceDiagram
  participant P as plant (paused under DSE)
  participant B as bridge / DSE (ROS env)
  participant S as policy_server (umi env, GPU 5)
  B->>P: step to observation tick t (StepSimulation, 1 physics step per call)
  P-->>B: RGB frame t + joint snapshot t (same mjData copy, same stamp)
  Note over B: [mask evaluator] pose the mirror from snapshot t,<br/>render oracle masks t (oracle_render.py)
  B->>S: obs frames {t-0.1 s, t} (+ masks)
  S-->>B: 16 x 10 action (EMA weights, deterministic)
  Note over B: decode -> 5-DoF IK projection -> JTC trajectory,<br/>virtual latency L_v = 0.216 s (108 ticks), cadence 6 steps = 0.6 s
  B->>P: goal delivered at t + L_v, takeover one tick later
```

- **Asynchronous evaluator** (`policy_rollout.py` + `rolling_executor.py`). It runs in
  real time with a rolling executor and latency compensation. It is kept for history.
  Its repeats were not reproducible, and a stale-clock bug was found in it
  (`sim_umi/train_results/2026-09-27_fov/DSE_DESIGN.md`).
- **Timing-controlled evaluator (DSE)** (`dse_rollout.py`). The plant is paused and
  stepped tick by tick, and every event is placed on an integer physics tick. Each
  episode passes hard gates: timeline invariants, arm/jaw continuity (lock check),
  exact observation ticks, the JTC takeover tick, and no anomalies. Renderer noise
  (+-1 grey level) is not controlled, so repeats diverge after a few plans. A pass is
  recorded as `GATE_PASS_<code hash>.json`.
- **Mask-capable evaluator** (`dse_rollout_masks.py`, used for B and its control). It
  wraps two methods of the DSE's bridge and changes none of its files. The masks come
  from the joint snapshot of the frame's own tick, via a plugin extension built into a
  separate overlay. The G0 control receives the same masks under ignored names. Its
  pass marker is `GATE_PASS_MASKS_<hash>.json`.

## 6. Metrics (sim_umi/scripts/definitive/aggregate.py)

- **corridor.** The ball entered the grasp corridor in the tool frame.
- **lifted.** Ball z > radius + 20 mm.
- **strict.** GT secure grasp: over a lifted stretch, the ball stays rigid in the tool
  frame within 4 mm for at least 0.5 s while the tool travels at least 30 mm.
- **bin.** The ball is in the bin.
- **abort.** Eight plans in a row the arm could not reach.
- **First-close geometry.** The ball's offset in the tool frame at close onset (depth,
  vertical, pitch), compared with the scripted expert.
