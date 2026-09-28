"""OMX-UMI GPU server additions.

This package is *additive* on top of the upstream Stanford UMI repository.
Nothing under ``diffusion_policy/`` or ``umi/`` is modified destructively; the
only upstream-adjacent files we add are two extra hydra configs
(``task/umi_omx.yaml`` and ``train_diffusion_unet_timm_omx_workspace.yaml``).

See ``README_GPU_WORKFLOW.md`` for the end-to-end workflow.
"""

__all__ = ["config", "collector_config", "data"]
