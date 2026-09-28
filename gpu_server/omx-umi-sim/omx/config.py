"""Experiment registry -- the single place to swap experimental choices.

Add an entry here and the whole pipeline follows: dataset build, inspection,
training and offline inference all take the same experiment name.

    python -m omx.cli list
    python -m omx.cli build   center_crop_v1
    python -m omx.cli inspect center_crop_v1
    python -m omx.cli train   center_crop_v1 --profile smoke
    python -m omx.cli train   center_crop_v1

Fairness rule for the section 25 / 26 comparisons: variants that are meant to be
compared MUST share ``collector_config``, ``seed``, ``val_ratio`` and the input
episode set, and differ only in ``rgb_mode``.  ``check_ab_comparable()`` enforces
that, and ``omx.cli ab`` reports it.
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import asdict, dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# machine-level constants
# --------------------------------------------------------------------------- #
#: Physical GPU this project is allowed to use.  Exported as CUDA_VISIBLE_DEVICES,
#: after which the process sees it as cuda:0 (handoff doc section 17).
GPU_DEVICE = os.environ.get("OMX_GPU_DEVICE", "5")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Config file written by the operator from config/cpu_sync.env.example.
CPU_SYNC_ENV = os.environ.get(
    "CPU_SYNC_ENV", os.path.expanduser("~/umi-gpu/config/cpu_sync.env"))


def _read_sync_env(path: str) -> dict:
    """Parse the KEY=VALUE lines of cpu_sync.env without sourcing a shell."""
    out: dict = {}
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                v = v.replace("${HOME}", os.path.expanduser("~"))
                v = v.replace("$HOME", os.path.expanduser("~"))
                out[k.strip()] = os.path.expanduser(v)
    except OSError:
        pass
    return out


#: The GPU-local mirror of the CPU's /srv/processed/v1, pulled by
#: scripts/sync_processed_from_cpu.sh.  Resolution order:
#:   1. OMX_PROCESSED_ROOT
#:   2. GPU_PROCESSED_ROOT in cpu_sync.env (so the sync script and the converter
#:      can never disagree about where the data is)
#:   3. the default below
#: The handoff spec names /data/dataset/v1. This box has no root and no /data
#: mount and /home has ~11 TB free, so only the root moves -- the processed/v1
#: namespace is kept so the path names what it mirrors:
#:     <cpu>:/srv/processed/v1  ->  <gpu>:~/omx_data/processed/v1
#: It also keeps the CPU mirror distinct from what the GPU generates (data/omx/).
DEFAULT_PROCESSED_ROOT = os.path.expanduser("~/omx_data/processed/v1")
PROCESSED_ROOT = (os.environ.get("OMX_PROCESSED_ROOT")
                  or _read_sync_env(CPU_SYNC_ENV).get("GPU_PROCESSED_ROOT")
                  or DEFAULT_PROCESSED_ROOT)

#: Everything this project writes lives under here.
DATA_ROOT = pathlib.Path(os.environ.get("OMX_DATA_ROOT", str(REPO_ROOT / "data" / "omx")))
ZARR_DIR = DATA_ROOT / "zarr"
INSPECT_DIR = DATA_ROOT / "inspect"
INFER_DIR = DATA_ROOT / "infer"
TRAIN_DIR = DATA_ROOT / "train"

WANDB_PROJECT = os.environ.get("OMX_WANDB_PROJECT", "omx-umi")

#: Fixed across every baseline run so the train/val episode split is identical
#: between dataset variants (handoff doc section 19).
SEED = 42
VAL_RATIO = 0.05

DEFAULT_COLLECTOR_CONFIG = "configs/collector/default.yaml"
DEFAULT_TRAIN_CONFIG = "train_diffusion_unet_timm_omx_workspace"


# --------------------------------------------------------------------------- #
# dataset variants
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DatasetVariant:
    """One built zarr.  Only ``rgb_mode`` should differ between A/B variants."""

    name: str
    rgb_mode: str = "center_crop"          # see omx.data.rgb_preprocess.RGB_MODES
    out_res: Tuple[int, int] = (224, 224)
    #: Source aspect this experiment was designed around.  The build refuses
    #: frames that disagree, because every mode still RUNS on the wrong aspect
    #: and just quietly becomes a different experiment.  None = accept anything.
    source_aspect: Optional[float] = 16 / 9
    allow_aspect_mismatch: bool = False
    pad_value: int = 0                     # letterbox fill
    collector_config: str = DEFAULT_COLLECTOR_CONFIG
    input_roots: Tuple[str, ...] = ()      # empty -> PROCESSED_ROOT
    input_format: str = "processed_v1"
    episode_pattern: Optional[str] = None  # regex filter on "<session>__<episode>"
    max_episodes: Optional[int] = None
    jpegxl_level: int = 99
    notes: str = ""

    @property
    def roots(self) -> Tuple[str, ...]:
        return self.input_roots or (PROCESSED_ROOT,)

    @property
    def zarr_path(self) -> pathlib.Path:
        return ZARR_DIR / f"{self.name}.zarr.zip"

    @property
    def meta_path(self) -> pathlib.Path:
        return ZARR_DIR / f"{self.name}.meta.json"

    def to_dict(self) -> Dict[str, object]:
        d = asdict(self)
        d["out_res"] = list(self.out_res)
        d["input_roots"] = list(self.roots)
        d["zarr_path"] = str(self.zarr_path)
        return d


@dataclass(frozen=True)
class Experiment:
    name: str
    dataset: DatasetVariant
    train_config: str = DEFAULT_TRAIN_CONFIG
    #: extra hydra overrides, e.g. ("training.num_epochs=200",)
    train_overrides: Tuple[str, ...] = ()
    #: fp16 roughly triples throughput on V100 (no bf16, no TF32 on sm_70) but is
    #: off by default so the baseline number is not confounded by precision.
    mixed_precision: str = "no"            # 'no' | 'fp16'
    seed: int = SEED
    val_ratio: float = VAL_RATIO
    tags: Tuple[str, ...] = ()
    notes: str = ""

    @property
    def zarr_path(self) -> pathlib.Path:
        return self.dataset.zarr_path

    @property
    def run_dir(self) -> pathlib.Path:
        return TRAIN_DIR / self.name

    def to_dict(self) -> Dict[str, object]:
        d = asdict(self)
        d["dataset"] = self.dataset.to_dict()
        d["train_overrides"] = list(self.train_overrides)
        d["tags"] = list(self.tags)
        return d


# --------------------------------------------------------------------------- #
# training profiles
# --------------------------------------------------------------------------- #
#: Short runs used to close the pipeline before spending hours (section 17).
TRAIN_PROFILES: Dict[str, Tuple[str, ...]] = {
    # 1. loader + 2. one forward + 3. one loss + 4. one backward
    "smoke": (
        "training.num_epochs=1",
        "training.max_train_steps=2",
        "training.max_val_steps=1",
        "training.checkpoint_every=1",
        "training.sample_every=1",
        "training.rollout_every=99999",
        "dataloader.batch_size=4",
        "val_dataloader.batch_size=4",
        "dataloader.num_workers=2",
        "val_dataloader.num_workers=2",
        "dataloader.persistent_workers=False",
        "val_dataloader.persistent_workers=False",
        "logging.mode=disabled",
    ),
    # 5. debug training: a couple of real epochs, W&B on, checkpoints written
    "debug": (
        "training.debug=True",
        "dataloader.batch_size=8",
        "val_dataloader.batch_size=8",
        "dataloader.num_workers=4",
        "val_dataloader.num_workers=4",
    ),
    # 6. full dataset training
    "full": (),
}


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
def _variant(name: str, rgb_mode: str, **kw) -> DatasetVariant:
    return DatasetVariant(name=name, rgb_mode=rgb_mode, **kw)


#: P0/P1 baseline plus the section 25/26 follow-ups.  Everything below shares the
#: same collector config, seed and episode set, so only the image differs.
EXPERIMENTS: Dict[str, Experiment] = {}


def register(exp: Experiment) -> Experiment:
    if exp.name in EXPERIMENTS:
        raise ValueError(f"duplicate experiment name {exp.name!r}")
    EXPERIMENTS[exp.name] = exp
    return exp


register(Experiment(
    name="omx_pick_raw_center_v1",
    dataset=_variant(
        "omx_pick_raw_center_v1", "center_crop",
        notes="Baseline v1: central square -> 224x224. From a 16:9 source that spends 43.75% of the width (HFOV 63.5 -> ~38 deg); the build refuses any other source aspect, because on 4:3 the same crop spends 25% (63.5 -> ~49.8) and the figure above would be a lie."),
    tags=("baseline", "center_crop", "stepA"),
    notes="handoff doc section 11 baseline v1. Build this first; everything else "
          "is compared against it.",
))

register(Experiment(
    name="omx_pick_matched_center_v1",
    dataset=_variant(
        "omx_pick_matched_center_v1", "matched_center_crop",
        notes="Step 1 B-arm: collector frames reprojected onto the robot wrist "
              "camera's virtual pinhole, then the same square FOV as the baseline."),
    tags=("step1", "camera_matching", "matched_center_crop"),
    notes="handoff doc section 25. Compare head-to-head with omx_pick_raw_center_v1; "
          "identical episodes/poses/split, only the image pipeline differs.",
))

register(Experiment(
    name="omx_pick_letterbox_v1",
    dataset=_variant(
        "omx_pick_letterbox_v1", "letterbox",
        notes="Step 2-2: full 16:9 HFOV preserved, width 224 -> ~224x126, "
              "padded top/bottom to 224x224. Tensor shape unchanged, so no ViT "
              "code change is needed."),
    tags=("step2", "fov", "letterbox"),
    notes="handoff doc section 26-2.",
))

register(Experiment(
    name="omx_pick_fit_rect_v1",
    dataset=_variant(
        "omx_pick_fit_rect_v1", "fit_rect", out_res=(224, 128),
        notes="Step 2-3: full horizontal FOV with no padding. The frame is cropped "
              "to the model's aspect ratio instead of the model's aspect ratio "
              "being forced onto the frame. Keeps the same horizontal FOV as "
              "letterbox while spending none of the tensor on pad, and 8x14 "
              "patches is 43% less attention than 14x14."),
    train_overrides={
        "config_name": "train_diffusion_unet_timm_omx_rect_workspace",
    },
    tags=("step2", "fov", "rect_vit"),
    notes="handoff doc section 26-3. NOT tensor-shape comparable with the 224x224 "
          "arms: check_ab_comparable() will flag the out_res difference, and that "
          "is correct -- this arm changes the encoder as well as the preprocessing, "
          "so a win here is not attributable to preprocessing alone.",
))

register(Experiment(
    name="omx_pick_stretch_v1",
    dataset=_variant(
        "omx_pick_stretch_v1", "stretch",
        notes="Control condition: aspect ratio deliberately destroyed. Useful to "
              "tell 'more FOV helps' apart from 'anything but the square crop helps'."),
    tags=("control", "stretch"),
    notes="Not on the critical path; build only if the letterbox result is ambiguous.",
))


# --------------------------------------------------------------------------- #
# synthetic integration fixtures
# --------------------------------------------------------------------------- #
# Generated by scripts/make_synthetic_processed_v1.py.  These exist so the whole
# P0/P1/P2 path can be exercised (and regression-tested) without the real
# dataset.  They are NEVER a result: every build from them is stamped
# dataset_synthetic=true in the W&B run config, and inspect_umi_zarr.py warns.
SYNTH_ROOT = os.environ.get("OMX_SYNTH_ROOT", str(DATA_ROOT / "synthetic_processed_v1"))

for _mode in ("center_crop", "letterbox", "matched_center_crop", "stretch",
              "fit_rect"):
    register(Experiment(
        name=f"synth_{_mode}",
        dataset=_variant(f"synth_{_mode}", _mode,
                         input_roots=(SYNTH_ROOT,),
                         out_res=(224, 128) if _mode == "fit_rect" else (224, 224),
                         source_aspect=None,   # plumbing test, not a result:
                                               # the FOV claim is not being made
                         notes="synthetic integration fixture -- not a result"),
        tags=("synthetic", "integration", _mode),
        notes="Pipeline fixture. Use for smoke tests and regressions only.",
    ))


def is_synthetic(exp: "Experiment") -> bool:
    return exp.name.startswith("synth_")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def get(name: str) -> Experiment:
    if name not in EXPERIMENTS:
        raise KeyError(
            f"unknown experiment {name!r}. Known: {', '.join(sorted(EXPERIMENTS))}")
    return EXPERIMENTS[name]


def list_experiments() -> List[Experiment]:
    return [EXPERIMENTS[k] for k in sorted(EXPERIMENTS)]


def check_ab_comparable(a: Experiment, b: Experiment) -> List[str]:
    """Report every difference that would invalidate an A/B comparison."""
    problems: List[str] = []
    if a.dataset.collector_config != b.dataset.collector_config:
        problems.append(
            f"collector_config differs: {a.dataset.collector_config} vs {b.dataset.collector_config}")
    if a.dataset.roots != b.dataset.roots:
        problems.append(f"input roots differ: {a.dataset.roots} vs {b.dataset.roots}")
    if a.dataset.episode_pattern != b.dataset.episode_pattern:
        problems.append(
            f"episode_pattern differs: {a.dataset.episode_pattern!r} vs {b.dataset.episode_pattern!r}")
    if a.dataset.max_episodes != b.dataset.max_episodes:
        problems.append(f"max_episodes differs: {a.dataset.max_episodes} vs {b.dataset.max_episodes}")
    if a.seed != b.seed:
        problems.append(f"seed differs: {a.seed} vs {b.seed}")
    if a.val_ratio != b.val_ratio:
        problems.append(f"val_ratio differs: {a.val_ratio} vs {b.val_ratio}")
    if a.dataset.out_res != b.dataset.out_res:
        problems.append(f"out_res differs: {a.dataset.out_res} vs {b.dataset.out_res}")
    if tuple(a.train_overrides) != tuple(b.train_overrides):
        problems.append(
            f"train_overrides differ: {list(a.train_overrides)} vs {list(b.train_overrides)}")
    if a.mixed_precision != b.mixed_precision:
        problems.append(f"mixed_precision differs: {a.mixed_precision} vs {b.mixed_precision}")
    if a.dataset.rgb_mode == b.dataset.rgb_mode:
        problems.append(
            f"both use rgb_mode={a.dataset.rgb_mode!r}; an A/B pair should differ here")
    return problems


def ensure_dirs() -> None:
    for d in (ZARR_DIR, INSPECT_DIR, INFER_DIR, TRAIN_DIR):
        d.mkdir(parents=True, exist_ok=True)
