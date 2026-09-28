# release_assets

These are the raw closed-loop rollout JSONs (> 5 MB each) behind the aggregates and
tables in `omx-umi-sim/`, kept at their original paths relative to the repository root.
Each holds every plan's observation audit, the policy I/O hashes, the timeline gates and
the EE track of every episode.

- **Uploading.** Put them on a GitHub Release, or track them with Git LFS.
- **Restoring the full layout.** `cp -r release_assets/sim_umi omx-umi-sim/`.
