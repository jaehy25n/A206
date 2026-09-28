"""G0 + oracle target/EE patch-relation FiLM (ablation B).

The policy itself is DiffusionUnetTimmPolicy unchanged -- same loss (L_diff
only), same sampling. The one change lives in the obs encoder
(TimmRelationFilmObsEncoder); this class only names the new module so the
workspace can load the shared G0 init around it and give it its own optimizer
group.
"""
from diffusion_policy.policy.diffusion_unet_timm_policy import DiffusionUnetTimmPolicy


class DiffusionUnetTimmRelationFilmPolicy(DiffusionUnetTimmPolicy):
    new_module_prefixes = ("obs_encoder.relation_film.",)

    def new_module_parameters(self):
        return self.obs_encoder.relation_film.parameters()

    def aux_provenance(self):
        enc = self.obs_encoder
        return {"ablation": "oracle_tip_relation_film", "ee_mask": enc.ee_mask_key,
                "target_mask": enc.target_mask_key, "valid_key": enc.target_valid_key,
                "min_target_px_hard_gate": enc.min_target_px, "relation_in_dim": enc.relation_in_dim,
                "relation_init_seed": enc.relation_init_seed,
                "film": "CLS' = CLS * (1 + gamma) + beta, last Linear zero-init, per-frame hard gate"}
