from typing import Optional
import os
import pathlib
import hydra
import copy
from hydra.core.hydra_config import HydraConfig
from omegaconf import OmegaConf
import dill
import torch
import threading


class BaseWorkspace:
    include_keys = tuple()
    exclude_keys = tuple()

    def __init__(self, cfg: OmegaConf, output_dir: Optional[str]=None):
        self.cfg = cfg
        self._output_dir = output_dir
        self._saving_thread = None

    @property
    def output_dir(self):
        output_dir = self._output_dir
        if output_dir is None:
            output_dir = HydraConfig.get().runtime.output_dir
        return output_dir
    
    def run(self):
        """
        Create any resource shouldn't be serialized as local variables
        """
        pass

    def wait_for_save(self):
        """Block until the checkpoint being written in the background is on
        disk under its final name."""
        t = getattr(self, '_saving_thread', None)
        if t is not None:
            t.join()
            self._saving_thread = None

    def save_checkpoint(self, path=None, tag='latest', 
            exclude_keys=None,
            include_keys=None,
            use_thread=True,
            extra=None):
        # One write at a time. Two checkpoints triggered one update apart
        # (step5985, step5986) would otherwise hold two full CPU copies of
        # the payload and race each other to disk.
        self.wait_for_save()
        if path is None:
            path = pathlib.Path(self.output_dir).joinpath('checkpoints', f'{tag}.ckpt')
        else:
            path = pathlib.Path(path)
        if exclude_keys is None:
            exclude_keys = tuple(self.exclude_keys)
        if include_keys is None:
            include_keys = tuple(self.include_keys) + ('_output_dir',)

        path.parent.mkdir(parents=False, exist_ok=True)
        payload = {
            'cfg': self.cfg,
            'state_dicts': dict(),
            'pickles': dict()
        } 

        for key, value in self.__dict__.items():
            if hasattr(value, 'state_dict') and hasattr(value, 'load_state_dict'):
                # modules, optimizers and samplers etc
                if key not in exclude_keys:
                    if use_thread:
                        payload['state_dicts'][key] = _copy_to_cpu(value.state_dict())
                    else:
                        payload['state_dicts'][key] = value.state_dict()
            elif key in include_keys:
                payload['pickles'][key] = dill.dumps(value)
        if extra is not None:
            # state that does not live in self.__dict__ -- the scheduler, the
            # gradient scaler, the EMA wrapper's counters, RNG states --
            # kept apart from state_dicts so load_payload does not try to
            # push it into attributes that do not exist yet at resume time
            payload['extra'] = _copy_to_cpu(extra) if use_thread else extra

        def _write():
            # Written under a temporary name and renamed only once complete,
            # so an interrupted write can never leave a truncated file under
            # the final checkpoint name.
            tmp = path.with_name(path.name + '.tmp')
            with tmp.open('wb') as f:
                torch.save(payload, f, pickle_module=dill)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)

        if use_thread:
            self._saving_thread = threading.Thread(target=_write)
            self._saving_thread.start()
        else:
            _write()
        return str(path.absolute())
    
    def get_checkpoint_path(self, tag='latest'):
        return pathlib.Path(self.output_dir).joinpath('checkpoints', f'{tag}.ckpt')

    def load_payload(self, payload, exclude_keys=None, include_keys=None, **kwargs):
        if exclude_keys is None:
            exclude_keys = tuple()
        if include_keys is None:
            include_keys = payload['pickles'].keys()

        for key, value in payload['state_dicts'].items():
            if key not in exclude_keys:
                self.__dict__[key].load_state_dict(value, **kwargs)
        for key in include_keys:
            if key in payload['pickles']:
                self.__dict__[key] = dill.loads(payload['pickles'][key])
    
    def load_checkpoint(self, path=None, tag='latest',
            exclude_keys=None, 
            include_keys=None, 
            **kwargs):
        if path is None:
            path = self.get_checkpoint_path(tag=tag)
        else:
            path = pathlib.Path(path)
        payload = torch.load(path.open('rb'), pickle_module=dill, **kwargs)
        self.load_payload(payload, 
            exclude_keys=exclude_keys, 
            include_keys=include_keys)
        return payload
    
    @classmethod
    def create_from_checkpoint(cls, path, 
            exclude_keys=None, 
            include_keys=None,
            **kwargs):
        payload = torch.load(open(path, 'rb'), pickle_module=dill)
        instance = cls(payload['cfg'])
        instance.load_payload(
            payload=payload, 
            exclude_keys=exclude_keys,
            include_keys=include_keys,
            **kwargs)
        return instance

    def save_snapshot(self, tag='latest'):
        """
        Quick loading and saving for reserach, saves full state of the workspace.

        However, loading a snapshot assumes the code stays exactly the same.
        Use save_checkpoint for long-term storage.
        """
        path = pathlib.Path(self.output_dir).joinpath('snapshots', f'{tag}.pkl')
        path.parent.mkdir(parents=False, exist_ok=True)
        torch.save(self, path.open('wb'), pickle_module=dill)
        return str(path.absolute())
    
    @classmethod
    def create_from_snapshot(cls, path):
        return torch.load(open(path, 'rb'), pickle_module=dill)


def _copy_to_cpu(x):
    if isinstance(x, torch.Tensor):
        # .to('cpu') is a no-op for a tensor that is already on the CPU, so it
        # used to hand the writer thread a reference, not a copy. AdamW keeps
        # its per-parameter step counters as CPU tensors and increments them
        # in place, so updates taken while the thread was still serializing
        # leaked into the file: a checkpoint triggered at update 3 came out
        # with parameters at steps 3, 4 and 5 -- and the historical baseline's
        # {5985: 235, 5986: 64} split is the same race. Clone CPU tensors.
        t = x.detach()
        return t.clone() if t.device.type == 'cpu' else t.to('cpu')
    elif isinstance(x, dict):
        result = dict()
        for k, v in x.items():
            result[k] = _copy_to_cpu(v)
        return result
    elif isinstance(x, list):
        return [_copy_to_cpu(k) for k in x]
    else:
        return copy.deepcopy(x)
