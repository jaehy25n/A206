# How this package was assembled (2026-09-28)

The original repository on the training host was not modified: nothing was deleted,
moved or rewritten. Everything below is a copy.

1. **The code tree.** `git archive` of `3c3d9aa` (branch `omx-gpu-baseline`), 1164
   tracked files.
2. **Files outside git.** Untracked or git-ignored project files, copied to the same
   relative paths:
   - figures and videos (png / jpg / gif / mp4);
   - Markdown, YAML and small JSON summaries (aggregates, audits, provenance, gate
     markers);
   - training and evaluation logs of 20 MB or less;
   - Python and shell files;
   - resolved hydra configs;
   - `conda_environment_train.yaml`.
   Excluded: `*.npz` frame / policy / cycle dumps, `*.pkl`, checkpoints, datasets,
   `wandb/`, notebook checkpoints, and the expanded `jetson_inference_source/`
   (shipped as its original tarball in `deliverables/jetson/`).
3. **Slimmed mask-evaluator JSONs.** The mask-capable evaluator's rollout JSONs
   (`sim_umi/eval_results/2026-09-28_dse_masks/*/nominal_*.json`) are slimmed copies.
   - The evaluator logged every non-RGB policy input into `trace[*].obs.lowdim`, which
     included the two 224x224 oracle masks per frame, so the files were 80 MB to 1.1 GB.
   - In these copies each mask array is replaced by `{"omitted_in_github_copy": true,
     "sha1_uint8", "shape"}`. Nothing else changes. 9 files, 3822 arrays; 3.65 GB became
     26 MB.
   - The full arrays remain in the original files on the host, and each run's
     `*_policy.npz` holds the exact arrays sent to the policy.
4. **`release_assets/`.** Next to this tree, not inside it, are the 47 raw rollout
   JSONs larger than 5 MB, at their original relative paths. They are the evidence
   behind the aggregates and are meant for a GitHub Release or Git LFS. Copy them back
   over this tree to restore the full layout.
5. **`external/`.** The patched `mujoco_ros2_control` camera plugin and its patches
   against upstream.
6. **`env/`, `colab/`.** Installable environment files: `requirements-train.txt`, which was
   verified by a from-scratch install; `environment-train.yml`; `environment-sim-ros.yml`.
   Also the Colab setup script and notebook, pip freeze and conda package lists of both host
   environments, and the host description (see ENVIRONMENT.md).
7. **`manifests/`.** sha256 and size of the datasets and checkpoints that are not
   shipped.
8. **New documents.** README.md, ARCHITECTURE.md, RESULTS.md, ENVIRONMENT.md, REPRODUCIBILITY.md,
   MEDIA.md, docs/INDEX.md, docs/git/COMMITS.md, and this file.
   - The upstream UMI README and license are kept under `docs/upstream/`.
   - The root `README.md` of the original repository is the upstream one; this
     package's README replaces it only here.

**Secrets check.** Private keys, API tokens, `.netrc`, `.env` files and the owner's
e-mail were searched for; none were found. The only IP addresses are the robot
addresses in upstream UMI's real-robot scripts. `sim_umi/reference/` contains the
owner's own recordings of the real cell (about 70 MB of video); remove it before
publishing if they are not meant to be public.
