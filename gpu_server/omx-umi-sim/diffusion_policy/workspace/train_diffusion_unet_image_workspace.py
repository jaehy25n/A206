if __name__ == "__main__":
    import sys
    import os
    import pathlib

    ROOT_DIR = str(pathlib.Path(__file__).parent.parent.parent)
    sys.path.append(ROOT_DIR)
    os.chdir(ROOT_DIR)

import os
import hydra
import torch
from omegaconf import OmegaConf
import pathlib
from torch.utils.data import DataLoader
import copy
import random
import wandb
import pickle
import tqdm
import numpy as np
import shutil
from diffusion_policy.workspace.base_workspace import BaseWorkspace
from diffusion_policy.policy.diffusion_unet_image_policy import DiffusionUnetImagePolicy
from diffusion_policy.dataset.base_dataset import BaseImageDataset, BaseDataset
from diffusion_policy.env_runner.base_image_runner import BaseImageRunner
from diffusion_policy.common.checkpoint_util import TopKCheckpointManager
from diffusion_policy.common.json_logger import JsonLogger
from diffusion_policy.common.pytorch_util import dict_apply, optimizer_to
from diffusion_policy.model.diffusion.ema_model import EMAModel
from diffusion_policy.model.common.lr_scheduler import get_scheduler
from accelerate import Accelerator

OmegaConf.register_new_resolver("eval", eval, replace=True)


def param_checksum(module, skip=('normalizer',)):
    """sha256 over every tensor of a state_dict, keys sorted, bytes as stored.

    The normalizer is left out on purpose: it is fitted to whichever dataset a
    run trains on, so two runs on different data are SUPPOSED to differ there,
    and folding it in would make the check meaningless. It is hashed
    separately so that difference is visible rather than hidden.
    """
    import hashlib
    h, hn = hashlib.sha256(), hashlib.sha256()
    sd = module.state_dict()
    for k in sorted(sd):
        v = sd[k]
        if not torch.is_tensor(v):
            continue
        b = v.detach().to('cpu').contiguous().numpy().tobytes()
        (hn if any(x in k for x in skip) else h).update(k.encode() + b)
    return h.hexdigest(), hn.hexdigest()


def shared_checksum(module, keys, skip=('normalizer',)):
    """sha256 over the module's tensors for the given keys only (sorted) -- the
    parameters an ablation shares with G0, whatever it adds."""
    import hashlib
    h = hashlib.sha256()
    sd = module.state_dict()
    for k in sorted(keys):
        if any(x in k for x in skip) or not torch.is_tensor(sd[k]):
            continue
        h.update(k.encode() + sd[k].detach().to('cpu').contiguous().numpy().tobytes())
    return h.hexdigest()


def file_identity(path):
    import hashlib
    p = pathlib.Path(path)
    st = p.stat()
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return {'path': str(p.resolve()), 'bytes': st.st_size,
            'mtime': st.st_mtime, 'sha256': h.hexdigest()}


def accelerate_unwrap(model):
    return getattr(model, 'module', model)


def git_commit():
    import subprocess
    try:
        root = pathlib.Path(__file__).resolve().parents[2]
        c = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                           capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(['git', '-C', str(root), 'status', '--porcelain',
                                '--untracked-files=no'],
                               capture_output=True, text=True).stdout.strip()
        return {'commit': c, 'dirty_tracked_files': bool(dirty)}
    except Exception as e:
        return {'commit': None, 'error': str(e)}


class TrainDiffusionUnetImageWorkspace(BaseWorkspace):
    include_keys = ['global_step', 'epoch', 'opt_steps',
                    'skipped_optimizer_steps', 'nonfinite_losses',
                    'init_checksum']
    exclude_keys = tuple()

    def __init__(self, cfg: OmegaConf, output_dir=None):
        super().__init__(cfg, output_dir=output_dir)

        # set seed
        seed = cfg.training.seed
        torch.manual_seed(seed)
        np.random.seed(seed)
        random.seed(seed)

        # configure model
        self.model: DiffusionUnetImagePolicy = hydra.utils.instantiate(cfg.policy)
        self.seed_init_checksum = param_checksum(self.model)[0]

        # Two runs meant to differ only in their data start from one saved
        # initial state rather than from two draws of the same seed, so that
        # "same initialisation" is a checked fact and not an assumption.
        init_path = cfg.training.get('init_state_path', None)
        self.init_state_source = 'seed'
        # An ablation that adds a module (it names it in new_module_prefixes)
        # loads the same G0 state strictly for every G0 key; the ONLY keys the
        # file may lack are the new module's own.
        self.new_module_prefixes = tuple(getattr(self.model, 'new_module_prefixes', ()) or ())
        self.shared_init_checksum = None
        if init_path:
            sd = torch.load(init_path, map_location='cpu')
            if self.new_module_prefixes:
                missing, unexpected = self.model.load_state_dict(sd, strict=False)
                new_keys = sorted(k for k in self.model.state_dict() if k.startswith(self.new_module_prefixes))
                if unexpected or sorted(missing) != new_keys or not new_keys:
                    raise RuntimeError(f"shared init mismatch: unexpected={unexpected} "
                                       f"missing-not-new={sorted(set(missing) - set(new_keys))}")
            else:
                self.model.load_state_dict(sd, strict=True)
            self.init_state_source = str(pathlib.Path(init_path).resolve())
            self.shared_init_checksum = shared_checksum(self.model, sd.keys())
        self.init_checksum = param_checksum(self.model)[0]

        self.ema_model: DiffusionUnetImagePolicy = None
        if cfg.training.use_ema:
            self.ema_model = copy.deepcopy(self.model)

        # configure training state
        # self.optimizer = hydra.utils.instantiate(
        #     cfg.optimizer, params=self.model.parameters())

        obs_encorder_lr = cfg.optimizer.lr
        if cfg.policy.obs_encoder.pretrained:
            obs_encorder_lr *= 0.1
            print('==> reduce pretrained obs_encorder\'s lr')
        # a new module gets a group of its own at the base LR; it is taken out
        # of the encoder group so groups 1-2 are exactly G0's
        new_params = list(self.model.new_module_parameters()) if self.new_module_prefixes else []
        new_ids = {id(p) for p in new_params}
        obs_encorder_params = list()
        for param in self.model.obs_encoder.parameters():
            if param.requires_grad and id(param) not in new_ids:
                obs_encorder_params.append(param)
        print(f'obs_encorder params: {len(obs_encorder_params)}')
        param_groups = [
            {'params': self.model.model.parameters()},
            {'params': obs_encorder_params, 'lr': obs_encorder_lr}
        ]
        if new_params:
            param_groups.append({'params': new_params, 'lr': cfg.optimizer.lr})
            print(f'new module params: {len(new_params)} tensors, '
                  f'{sum(p.numel() for p in new_params)} values, lr {cfg.optimizer.lr}')
        # self.optimizer = hydra.utils.instantiate(
        #     cfg.optimizer, params=param_groups)
        optimizer_cfg = OmegaConf.to_container(cfg.optimizer, resolve=True)
        optimizer_cfg.pop('_target_')
        self.optimizer = torch.optim.AdamW(
            params=param_groups,
            **optimizer_cfg
        )

        # configure training state
        self.global_step = 0
        # Optimizer updates, counted separately from global_step. They are not
        # the same number: global_step skips the last batch of each epoch and
        # drifts across a resume, and a comparison between two runs on
        # different-sized datasets has to be made on updates.
        self.opt_steps = 0
        self.epoch = 0

        # Updates the optimizer actually applied are counted in opt_steps;
        # updates the gradient scaler threw away for overflow are counted
        # here and nowhere else.
        self.skipped_optimizer_steps = 0
        self.nonfinite_losses = 0

        # The optimizer is always saved. Whether a run resumes and whether
        # its checkpoints can be resumed from are separate questions; tying
        # the second to the first is how an entire run once came out with
        # checkpoints that could only ever be evaluated, never continued.
        if cfg.training.get('exclude_optimizer_from_checkpoint', False):
            self.exclude_keys = ['optimizer']

    # ----------------------------------------------------------- run state --
    def _raw_scheduler(self):
        sch = self._rt.lr_scheduler
        return getattr(sch, 'scheduler', sch)

    def _checkpoint_extra(self):
        """State that lives outside self.__dict__ but is needed to continue.

        The scheduler and the gradient scaler are created inside run(), and
        the EMA wrapper's step counter lives on the wrapper, not on the
        averaged model -- so none of them are reached by save_checkpoint's
        walk over attributes. Without this, a checkpoint restores weights and
        loses where in training they were.
        """
        rt = self._rt
        acc = rt.accelerator
        scaler = getattr(acc, 'scaler', None)
        ema = rt.ema
        return {
            'format': 'definitive-v1',
            'lr_scheduler': self._raw_scheduler().state_dict(),
            'scaler': (scaler.state_dict() if scaler is not None else None),
            'ema': (None if ema is None else {
                'optimization_step': int(ema.optimization_step),
                'decay': float(ema.decay)}),
            'counters': {
                'opt_steps': int(self.opt_steps),
                'global_step': int(self.global_step),
                'epoch': int(self.epoch),
                'batch_idx_in_epoch': int(rt.batch_idx),
                'skipped_optimizer_steps': int(self.skipped_optimizer_steps),
                'nonfinite_losses': int(self.nonfinite_losses)},
            'rng': {
                'python': random.getstate(),
                'numpy': np.random.get_state(),
                'torch_cpu': torch.get_rng_state(),
                'torch_cuda': torch.cuda.get_rng_state_all()
                              if torch.cuda.is_available() else None},
            'provenance': rt.provenance,
        }

    def _write_step_provenance(self, tag, ckpt_path):
        """Everything needed to say where this checkpoint sits in training,
        written next to it in plain JSON.

        Taken AFTER the optimizer, the scheduler and the EMA have all applied
        the update being counted, so every counter below describes the same
        instant. (The first version of this ran before the EMA step and
        reported an EMA count one short of the optimizer's.)
        """
        import collections, json as _json
        rt = self._rt
        n_trainable = sum(1 for q in accelerate_unwrap(self.model).parameters()
                          if q.requires_grad)
        hist = collections.Counter(int(v['step'])
                                   for v in self.optimizer.state.values()
                                   if 'step' in v)
        sch = self._raw_scheduler().state_dict()
        scaler = getattr(rt.accelerator, 'scaler', None)
        out = {
            'tag': tag,
            'checkpoint': str(ckpt_path),
            'opt_steps': int(self.opt_steps),
            'global_step': int(self.global_step),
            'epoch': int(self.epoch),
            'batch_idx_in_epoch': int(rt.batch_idx),
            'trainable_parameters': int(n_trainable),
            'params_with_optimizer_state': int(sum(hist.values())),
            'param_step_histogram': {str(k): int(v) for k, v in sorted(hist.items())},
            'lr_group0': float(self.optimizer.param_groups[0]['lr']),
            'lr_group1': float(self.optimizer.param_groups[1]['lr']),
            'scheduler_state': {k: (v if isinstance(v, (int, float, str, bool, type(None)))
                                    else ([float(x) for x in v] if isinstance(v, (list, tuple))
                                          and all(isinstance(x, (int, float)) for x in v)
                                          else str(type(v).__name__)))
                                for k, v in sch.items()},
            'ema_update_count': (int(rt.ema.optimization_step) if rt.ema is not None else None),
            'ema_decay': (float(rt.ema.decay) if rt.ema is not None else None),
            'scaler': (None if scaler is None else
                       {k: (float(v) if isinstance(v, (int, float)) else str(v))
                        for k, v in scaler.state_dict().items()}),
            'skipped_optimizer_steps': int(self.skipped_optimizer_steps),
            'nonfinite_losses': int(self.nonfinite_losses),
            'evaluation_weight_source': 'ema_model' if rt.ema is not None else 'model',
            **rt.provenance,
        }
        d = pathlib.Path(self.output_dir).joinpath('checkpoints')
        d.mkdir(parents=True, exist_ok=True)
        d.joinpath(f'{tag}.provenance.json').write_text(_json.dumps(out, indent=1))
        return out

    def run(self):
        cfg = copy.deepcopy(self.cfg)

        # Mixed precision through Accelerate's native AMP: autocast around the
        # forward and a GradScaler around backward/step. The weights and the
        # optimizer state stay float32. 'no' keeps the old behaviour exactly.
        mixed_precision = cfg.training.get('mixed_precision', 'no') or 'no'
        accelerator = Accelerator(log_with='wandb', mixed_precision=mixed_precision)
        wandb_cfg = OmegaConf.to_container(cfg.logging, resolve=True)
        wandb_cfg.pop('project')
        accelerator.init_trackers(
            project_name=cfg.logging.project,
            config=OmegaConf.to_container(cfg, resolve=True),
            init_kwargs={"wandb": wandb_cfg}
        )

        # resume training
        resume_extra, resumed_from = None, None
        resume_path = cfg.training.get('resume_path', None)
        if resume_path or cfg.training.resume:
            ckpt = pathlib.Path(resume_path) if resume_path else self.get_checkpoint_path()
            if ckpt.is_file():
                accelerator.print(f"Resuming from checkpoint {ckpt}")
                payload = self.load_checkpoint(path=ckpt)
                resume_extra = payload.get('extra')
                resumed_from = str(ckpt)
                # a checkpoint without an update counter predates it; its
                # position is only known through global_step
                self._resume_has_opt_steps = 'opt_steps' in payload['pickles']
            elif resume_path:
                raise FileNotFoundError(f"resume_path does not exist: {ckpt}")

        # configure dataset
        dataset: BaseImageDataset
        dataset = hydra.utils.instantiate(cfg.task.dataset)
        assert isinstance(dataset, BaseImageDataset) or isinstance(dataset, BaseDataset)
        twin_path = cfg.training.get('twin_probe_path', None)
        if twin_path:
            dataset.emit_sample_index = True
        # Opt-in: a generator of its own for the sampler (and the workers' base
        # seed), so that two runs whose model construction draws different
        # amounts of randomness still see the same samples in the same order.
        # Without the key the DataLoader is built exactly as before.
        dl_kwargs = dict(cfg.dataloader)
        dl_seed = cfg.training.get('dataloader_seed', None)
        if dl_seed is not None:
            dl_gen = torch.Generator()
            dl_gen.manual_seed(int(dl_seed))
            dl_kwargs['generator'] = dl_gen
        train_dataloader = DataLoader(dataset, **dl_kwargs)

        # compute normalizer on the main process and save to disk
        normalizer_path = os.path.join(self.output_dir, 'normalizer.pkl')
        if accelerator.is_main_process:
            normalizer = dataset.get_normalizer()
            pickle.dump(normalizer, open(normalizer_path, 'wb'))

        # load normalizer on all processes
        accelerator.wait_for_everyone()
        normalizer = pickle.load(open(normalizer_path, 'rb'))

        # configure validation dataset
        val_dataset = dataset.get_validation_dataset()
        val_dataloader = DataLoader(val_dataset, **cfg.val_dataloader)
        print('train dataset:', len(dataset), 'train dataloader:', len(train_dataloader))
        print('val dataset:', len(val_dataset), 'val dataloader:', len(val_dataloader))

        self.model.set_normalizer(normalizer)
        if cfg.training.use_ema:
            self.ema_model.set_normalizer(normalizer)

        # configure lr scheduler
        lr_scheduler = get_scheduler(
            cfg.training.lr_scheduler,
            optimizer=self.optimizer,
            num_warmup_steps=cfg.training.lr_warmup_steps,
            # The cosine horizon is dataset-size dependent: it is batches per
            # epoch times epochs, and a dataset three and a half times the
            # size has three and a half times as many batches. Two runs
            # compared at the same optimizer step would then be at completely
            # different points of the same schedule -- 1.57x apart at step
            # 5985 here. An explicit total lets the second run be given the
            # first one's horizon, so the LR each optimizer step sees is the
            # same one. Left unset, the behaviour is exactly as before.
            num_training_steps=(
                int(cfg.training.lr_scheduler_total_steps)
                if cfg.training.get('lr_scheduler_total_steps') else
                (len(train_dataloader) * cfg.training.num_epochs)
                // cfg.training.gradient_accumulate_every),
            # pytorch assumes stepping LRScheduler every epoch
            # however huggingface diffusers steps it every batch.
            # Positioned by successful optimizer updates, the thing the
            # schedule is a function of; global_step skips a batch per epoch
            # and drifted from it by three across the baseline's resumes.
            last_epoch=(self.opt_steps
                        if (resumed_from is None or getattr(self, '_resume_has_opt_steps', False))
                        else self.global_step) - 1
        )
        if resume_extra is not None and resume_extra.get('lr_scheduler') is not None:
            lr_scheduler.load_state_dict(resume_extra['lr_scheduler'])
            # the optimizer's live LR must be the one the restored schedule
            # says, or the first update after a resume runs at the wrong rate
            for g, lr in zip(self.optimizer.param_groups, lr_scheduler.get_last_lr()):
                g['lr'] = lr

        # configure ema
        ema: EMAModel = None
        if cfg.training.use_ema:
            ema = hydra.utils.instantiate(
                cfg.ema,
                model=self.ema_model)
            if resume_extra is not None and resume_extra.get('ema') is not None:
                ema.optimization_step = int(resume_extra['ema']['optimization_step'])
                ema.decay = float(resume_extra['ema']['decay'])

        # configure env
        env_runner: BaseImageRunner
        env_runner = hydra.utils.instantiate(
            cfg.task.env_runner,
            output_dir=self.output_dir)
        assert isinstance(env_runner, BaseImageRunner)

        # # configure logging
        # wandb_run = wandb.init(
        #     dir=str(self.output_dir),
        #     config=OmegaConf.to_container(cfg, resolve=True),
        #     **cfg.logging
        # )
        # wandb.config.update(
        #     {
        #         "output_dir": self.output_dir,
        #     }
        # )

        # configure checkpoint
        topk_manager = TopKCheckpointManager(
            save_dir=os.path.join(self.output_dir, 'checkpoints'),
            **cfg.checkpoint.topk
        )

        # device transfer
        # device = torch.device(cfg.training.device)
        # self.model.to(device)
        # if self.ema_model is not None:
        #     self.ema_model.to(device)
        # optimizer_to(self.optimizer, device)

        # accelerator
        train_dataloader, val_dataloader, self.model, self.optimizer, lr_scheduler = accelerator.prepare(
            train_dataloader, val_dataloader, self.model, self.optimizer, lr_scheduler
        )
        device = self.model.device
        if self.ema_model is not None:
            self.ema_model.to(device)

        scaler = getattr(accelerator, 'scaler', None)
        if resume_extra is not None and scaler is not None and resume_extra.get('scaler'):
            scaler.load_state_dict(resume_extra['scaler'])

        # everything a checkpoint or a sidecar needs to describe the run
        import types, json as _json, socket, time as _time
        ds_path = cfg.task.get('dataset_path', None)
        provenance = {
            'git': git_commit(),
            'hostname': socket.gethostname(),
            'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES'),
            'mixed_precision': str(accelerator.mixed_precision),
            'batch_size': int(cfg.dataloader.batch_size),
            'gradient_accumulate_every': int(cfg.training.gradient_accumulate_every),
            'dataset': (file_identity(ds_path) if ds_path else None),
            'val_ratio': float(cfg.task.dataset.get('val_ratio', 0.0)),
            'train_samples': int(len(dataset)),
            'dataloader_len': int(len(train_dataloader)),
            'lr_scheduler_total_steps': cfg.training.get('lr_scheduler_total_steps', None),
            'lr_warmup_steps': int(cfg.training.lr_warmup_steps),
            'init_state_source': self.init_state_source,
            'init_checksum': self.init_checksum,
            'seed_init_checksum': self.seed_init_checksum,
            'shared_init_checksum': self.shared_init_checksum,
            'new_module_prefixes': list(self.new_module_prefixes),
            'ablation': (accelerate_unwrap(self.model).aux_provenance()
                         if hasattr(accelerate_unwrap(self.model), 'aux_provenance') else None),
            'sidecars': getattr(dataset, 'sidecar_provenance', None),
            'optimizer_groups': [{'n_tensors': len(g['params']), 'initial_lr': g.get('initial_lr', g['lr'])} for g in self.optimizer.param_groups],
            'resumed_from': resumed_from,
        }
        self._rt = types.SimpleNamespace(accelerator=accelerator, lr_scheduler=lr_scheduler,
                                         ema=ema, batch_idx=0, provenance=provenance)

        # Prove the precision the run actually trains in, rather than the one
        # it was asked for: record, from inside the forward, whether autocast
        # is on and what dtype the denoiser produces.
        probe = {}
        def _probe(mod, inp, out):
            # keyed on its own field: other probes may already have written
            if 'autocast_enabled' not in probe:
                probe['autocast_enabled'] = bool(torch.is_autocast_enabled())
                o = out[0] if isinstance(out, (tuple, list)) else out
                probe['denoiser_output_dtype'] = str(getattr(o, 'dtype', None))
        _probe_handle = accelerate_unwrap(self.model).model.register_forward_hook(_probe)
        # and what the image path really is at the first step: the ViT token
        # sequence and the encoder's output width (records only)
        _probe_extra = []
        _enc = accelerate_unwrap(self.model).obs_encoder
        def _probe_enc(mod, inp, out):
            if 'global_cond_shape' not in probe:
                probe['global_cond_shape'] = list(out.shape)
        _probe_extra.append(_enc.register_forward_hook(_probe_enc))
        for _k, _m in _enc.key_model_map.items():
            if hasattr(_m, 'blocks'):
                def _probe_tok(mod, inp, _k=_k):
                    probe.setdefault(f'{_k}_vit_tokens', list(inp[0].shape))
                _probe_extra.append(_m.blocks[0].register_forward_pre_hook(_probe_tok))
        # opt-in: fingerprints of the first N batches, to compare sample order
        # between runs (eef_pos and action carry no augmentation noise)
        fp_n = int(cfg.training.get('log_batch_fingerprints', 0) or 0)
        fp_rows = []
        twin = None
        if twin_path:
            from diffusion_policy.workspace.twin_probe import TwinProbe
            twin = TwinProbe(twin_path, int(cfg.training.get('twin_probe_steps', 20)), accelerate_unwrap(self.model))

        if resume_extra is not None and resume_extra.get('rng') is not None:
            r = resume_extra['rng']
            random.setstate(r['python'])
            np.random.set_state(r['numpy'])
            torch.set_rng_state(r['torch_cpu'])
            if r.get('torch_cuda') is not None and torch.cuda.is_available():
                torch.cuda.set_rng_state_all(r['torch_cuda'])
            import hashlib as _hl
            provenance['rng_restored'] = {
                'torch_cpu_sha256': _hl.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest(),
                'saved_torch_cpu_sha256': _hl.sha256(r['torch_cpu'].numpy().tobytes()).hexdigest()}

        checkpoint_at = [int(x) for x in (cfg.training.get('checkpoint_at_steps') or [])]
        max_opt_steps = cfg.training.get('max_opt_steps', None)
        max_opt_steps = int(max_opt_steps) if max_opt_steps else None
        max_skip_total = int(cfg.training.get('max_skipped_updates', 50))
        max_skip_consec = int(cfg.training.get('max_consecutive_skips', 10))
        consecutive_skips = 0
        stop_training = False
        run_prov_path = pathlib.Path(self.output_dir).joinpath('run_provenance.json')
        run_prov = dict(provenance, config=OmegaConf.to_container(cfg, resolve=True),
                        started=_time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                        opt_steps_at_start=int(self.opt_steps),
                        ema_checksum_matches_model_at_start=(
                            None if self.ema_model is None else
                            param_checksum(self.ema_model)[0]
                            == param_checksum(accelerate_unwrap(self.model))[0]))
        run_prov_path.write_text(_json.dumps(run_prov, indent=1, default=str))

        # save batch for sampling
        train_sampling_batch = None

        if cfg.training.debug:
            cfg.training.num_epochs = 2
            cfg.training.max_train_steps = 3
            cfg.training.max_val_steps = 3
            cfg.training.rollout_every = 1
            cfg.training.checkpoint_every = 1
            cfg.training.val_every = 1
            cfg.training.sample_every = 1

        # training loop
        log_path = os.path.join(self.output_dir, 'logs.json.txt')
        with JsonLogger(log_path) as json_logger:
            for local_epoch_idx in range(cfg.training.num_epochs):
                self.model.train()

                step_log = dict()
                # ========= train for this epoch ==========
                if cfg.training.freeze_encoder:
                    self.model.obs_encoder.eval()
                    self.model.obs_encoder.requires_grad_(False)

                train_losses = list()
                with tqdm.tqdm(train_dataloader, desc=f"Training epoch {self.epoch}", 
                        leave=False, mininterval=cfg.training.tqdm_interval_sec) as tepoch:
                    for batch_idx, batch in enumerate(tepoch):
                        if fp_n and len(fp_rows) < fp_n:
                            import hashlib as _hl
                            def _h(x):
                                return _hl.sha1(x.detach().cpu().contiguous().numpy().tobytes()).hexdigest()[:16]
                            fp_rows.append({
                                'n': len(fp_rows), 'epoch': self.epoch, 'batch_idx': batch_idx,
                                'eef_pos': _h(batch['obs']['robot0_eef_pos']),
                                'action': _h(batch['action']),
                                'start_noise_obs': _h(batch['obs']['robot0_eef_rot_axis_angle_wrt_start']),
                                'first_eef_pos': [round(float(v), 6) for v in batch['obs']['robot0_eef_pos'][0, -1]]})
                            if len(fp_rows) == fp_n and accelerator.is_main_process:
                                pathlib.Path(self.output_dir).joinpath('batch_fingerprints.json').write_text(
                                    _json.dumps(fp_rows, indent=1))
                        if 'camera0_rgb' in batch.get('obs', {}) and 'batch_camera0_rgb_shape' not in probe:
                            probe['batch_camera0_rgb_shape'] = list(batch['obs']['camera0_rgb'].shape)
                        # device transfer
                        batch = dict_apply(batch, lambda x: x.to(device, non_blocking=True))
                        
                        # always use the latest batch
                        train_sampling_batch = batch

                        self._rt.batch_idx = batch_idx
                        if twin is not None:
                            twin.begin(self.global_step, batch)
                        # compute loss
                        raw_loss = self.model(batch)
                        loss_terms = getattr(accelerate_unwrap(self.model), 'last_loss_terms', None)
                        if twin is not None:
                            twin.after_forward(loss_terms['loss_diff'] if loss_terms else raw_loss.item())
                        if not torch.isfinite(raw_loss.detach()).all():
                            self.nonfinite_losses += 1
                            pathlib.Path(self.output_dir).joinpath('HARD_FAIL.txt').write_text(
                                f"non-finite loss {raw_loss.item()} at opt_steps={self.opt_steps} "
                                f"epoch={self.epoch} batch={batch_idx}\n")
                            raise RuntimeError(
                                f"HARD FAIL: non-finite loss at opt_steps={self.opt_steps}")
                        loss = raw_loss / cfg.training.gradient_accumulate_every
                        # through the accelerator, so that under fp16 the loss is
                        # scaled before backward and the scaler can unscale it
                        accelerator.backward(loss)

                        # step optimizer
                        if self.global_step % cfg.training.gradient_accumulate_every == 0:
                            self.optimizer.step()
                            skipped = bool(getattr(self.optimizer, 'step_was_skipped', False))
                            self.optimizer.zero_grad()
                            # AcceleratedScheduler does not advance when the
                            # optimizer step was skipped, so the schedule stays a
                            # function of updates actually applied
                            lr_scheduler.step()
                            if skipped:
                                self.skipped_optimizer_steps += 1
                                consecutive_skips += 1
                                if (consecutive_skips >= max_skip_consec
                                        or self.skipped_optimizer_steps > max_skip_total):
                                    pathlib.Path(self.output_dir).joinpath('HARD_FAIL.txt').write_text(
                                        f"gradient scaler collapse: {self.skipped_optimizer_steps} "
                                        f"skipped updates, {consecutive_skips} consecutive, at "
                                        f"opt_steps={self.opt_steps}\n")
                                    raise RuntimeError("HARD FAIL: repeated AMP overflow")
                            else:
                                consecutive_skips = 0
                                # The order is the definition of a checkpoint:
                                # optimizer, scheduler, EMA, THEN the count, THEN
                                # anything that is saved. A step-N checkpoint is the
                                # state after exactly N applied updates, in all of
                                # its parts.
                                if cfg.training.use_ema:
                                    ema.step(accelerator.unwrap_model(self.model))
                                self.opt_steps += 1
                                if self.opt_steps == 1 and probe:
                                    run_prov.update({'amp_probe': dict(probe)})
                                    run_prov_path.write_text(_json.dumps(run_prov, indent=1, default=str))
                                    _probe_handle.remove()
                                    for _hdl in _probe_extra:
                                        _hdl.remove()
                                if self.opt_steps in checkpoint_at:
                                    tag = f'step{self.opt_steps}'
                                    path = self.save_checkpoint(tag=tag, extra=self._checkpoint_extra())
                                    self._write_step_provenance(tag, path)
                                if max_opt_steps is not None and self.opt_steps >= max_opt_steps:
                                    stop_training = True
                            if twin is not None:
                                twin.end(self.opt_steps, skipped, lr_scheduler.get_last_lr())

                        # logging
                        raw_loss_cpu = raw_loss.item()
                        tepoch.set_postfix(loss=raw_loss_cpu, refresh=False)
                        train_losses.append(raw_loss_cpu)
                        step_log = {
                            'train_loss': raw_loss_cpu,
                            'global_step': self.global_step,
                            'epoch': self.epoch,
                            'lr': lr_scheduler.get_last_lr()[0]
                        }
                        if loss_terms:
                            step_log.update(loss_terms)
                            step_log['opt_steps'] = int(self.opt_steps)

                        is_last_batch = (batch_idx == (len(train_dataloader)-1))
                        if not is_last_batch:
                            # log of last step is combined with validation and rollout
                            accelerator.log(step_log, step=self.global_step)
                            json_logger.log(step_log)
                            self.global_step += 1

                        if (cfg.training.max_train_steps is not None) \
                            and batch_idx >= (cfg.training.max_train_steps-1):
                            break
                        if stop_training:
                            break

                # at the end of each epoch
                # replace train_loss with epoch average
                train_loss = np.mean(train_losses)
                step_log['train_loss'] = train_loss

                # ========= eval for this epoch ==========
                policy = accelerator.unwrap_model(self.model)
                if cfg.training.use_ema:
                    policy = self.ema_model
                policy.eval()

                # run rollout
                if (self.epoch % cfg.training.rollout_every) == 0:
                    runner_log = env_runner.run(policy)
                    # log all
                    step_log.update(runner_log)

                # run validation
                # if (self.epoch % cfg.training.val_every) == 0 and len(val_dataloader) > 0 and accelerator.is_main_process:
                #     with torch.no_grad():
                #         val_losses = list()
                #         with tqdm.tqdm(val_dataloader, desc=f"Validation epoch {self.epoch}", 
                #                 leave=False, mininterval=cfg.training.tqdm_interval_sec) as tepoch:
                #             for batch_idx, batch in enumerate(tepoch):
                #                 batch = dict_apply(batch, lambda x: x.to(device, non_blocking=True))
                #                 loss = self.model(batch)
                #                 val_losses.append(loss)
                #                 if (cfg.training.max_val_steps is not None) \
                #                     and batch_idx >= (cfg.training.max_val_steps-1):
                #                     break
                #         if len(val_losses) > 0:
                #             val_loss = torch.mean(torch.tensor(val_losses)).item()
                #             # log epoch average validation loss
                #             step_log['val_loss'] = val_loss
                
                def log_action_mse(step_log, category, pred_action, gt_action):
                    B, T, _ = pred_action.shape
                    pred_action = pred_action.view(B, T, -1, 10)
                    gt_action = gt_action.view(B, T, -1, 10)
                    step_log[f'{category}_action_mse_error'] = torch.nn.functional.mse_loss(pred_action, gt_action)
                    step_log[f'{category}_action_mse_error_pos'] = torch.nn.functional.mse_loss(pred_action[..., :3], gt_action[..., :3])
                    step_log[f'{category}_action_mse_error_rot'] = torch.nn.functional.mse_loss(pred_action[..., 3:9], gt_action[..., 3:9])
                    step_log[f'{category}_action_mse_error_width'] = torch.nn.functional.mse_loss(pred_action[..., 9], gt_action[..., 9])
                # run diffusion sampling on a training batch
                if (self.epoch % cfg.training.sample_every) == 0 and accelerator.is_main_process:
                    with torch.no_grad():
                        # sample trajectory from training set, and evaluate difference
                        batch = dict_apply(train_sampling_batch, lambda x: x.to(device, non_blocking=True))
                        gt_action = batch['action']
                        pred_action = policy.predict_action(batch['obs'], None)['action_pred']
                        log_action_mse(step_log, 'train', pred_action, gt_action)

                        if len(val_dataloader) > 0:
                            val_sampling_batch = next(iter(val_dataloader))
                            batch = dict_apply(val_sampling_batch, lambda x: x.to(device, non_blocking=True))
                            gt_action = batch['action']
                            pred_action = policy.predict_action(batch['obs'], None)['action_pred']
                            log_action_mse(step_log, 'val', pred_action, gt_action)

                        del batch
                        del gt_action
                        del pred_action
                
                # checkpoint
                if (self.epoch % cfg.training.checkpoint_every) == 0 and accelerator.is_main_process:
                    # unwrap the model to save ckpt
                    model_ddp = self.model
                    self.model = accelerator.unwrap_model(self.model)

                    # checkpointing
                    if cfg.checkpoint.save_last_ckpt:
                        self.save_checkpoint(extra=self._checkpoint_extra())
                    if cfg.checkpoint.save_last_snapshot:
                        self.save_snapshot()

                    # sanitize metric names
                    metric_dict = dict()
                    for key, value in step_log.items():
                        new_key = key.replace('/', '_')
                        metric_dict[new_key] = value
                    
                    # We can't copy the last checkpoint here
                    # since save_checkpoint uses threads.
                    # therefore at this point the file might have been empty!
                    topk_ckpt_path = topk_manager.get_ckpt_path(metric_dict)

                    if topk_ckpt_path is not None:
                        self.save_checkpoint(path=topk_ckpt_path, extra=self._checkpoint_extra())

                    # recover the DDP model
                    self.model = model_ddp
                # ========= eval end for this epoch ==========
                # end of epoch
                # log of last step is combined with validation and rollout
                accelerator.log(step_log, step=self.global_step)
                json_logger.log(step_log)
                self.global_step += 1
                self.epoch += 1
                if stop_training:
                    break

        # the last checkpoint is written in the background; it is not a
        # checkpoint until it is on disk under its final name
        self.wait_for_save()
        run_prov.update({'finished': _time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                         'opt_steps_at_end': int(self.opt_steps),
                         'skipped_optimizer_steps': int(self.skipped_optimizer_steps),
                         'nonfinite_losses': int(self.nonfinite_losses),
                         'stopped_by_max_opt_steps': bool(stop_training)})
        run_prov_path.write_text(_json.dumps(run_prov, indent=1, default=str))
        accelerator.end_training()

@hydra.main(
    version_base=None,
    config_path=str(pathlib.Path(__file__).parent.parent.joinpath("config")), 
    config_name=pathlib.Path(__file__).stem)
def main(cfg):
    workspace = TrainDiffusionUnetImageWorkspace(cfg)
    workspace.run()

if __name__ == "__main__":
    main()
