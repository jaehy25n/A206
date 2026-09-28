#!/usr/bin/env bash
# Colab / any fresh Linux + NVIDIA GPU: a Python 3.9 environment with this project's
# training stack, without touching the system Python (Colab's own Python may be 3.12,
# for which torch 2.1.0 has no wheels).
#   bash colab/setup_colab.sh            # creates ./.mamba/envs/omx (about 6 GB)
#   source colab/activate.sh             # then: python train.py ...
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT_PREFIX=${MAMBA_ROOT_PREFIX:-$PWD/.mamba}
BIN=$ROOT_PREFIX/bin
mkdir -p $BIN
if [ ! -x $BIN/micromamba ]; then
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C $ROOT_PREFIX bin/micromamba
fi
export MAMBA_ROOT_PREFIX=$ROOT_PREFIX
$BIN/micromamba create -y -n omx -c conda-forge python=3.9 pip av=10.0 gym=0.21.0
ENV=$ROOT_PREFIX/envs/omx
$ENV/bin/python -m pip install -r env/requirements-train.txt
cat > colab/activate.sh <<A
export PATH=$ENV/bin:\$PATH
export MUJOCO_GL=egl
export PYTHONNOUSERSITE=1
A
$ENV/bin/python - <<'PY'
import torch, timm, diffusers, zarr, imagecodecs, mujoco, cv2
print("torch", torch.__version__, "cuda available", torch.cuda.is_available())
print("timm", timm.__version__, "diffusers", diffusers.__version__, "zarr", zarr.__version__,
      "imagecodecs", imagecodecs.__version__, "jpegxl", imagecodecs.JPEGXL.available, "mujoco", mujoco.__version__, "cv2", cv2.__version__)
PY
echo "done: source colab/activate.sh"
