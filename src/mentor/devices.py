"""Inference hardware selection, separate from the torch probe for deterministic checks."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DeviceProbe:
    cuda: bool
    mps: bool
    cuda_bfloat16: bool


@dataclass(frozen=True)
class DeviceSelection:
    device: Literal["cuda", "mps", "cpu"]
    precision: Literal["bfloat16", "float32"]


def select_device(probe: DeviceProbe) -> DeviceSelection:
    if probe.cuda:
        return DeviceSelection("cuda", "bfloat16" if probe.cuda_bfloat16 else "float32")
    return DeviceSelection("mps" if probe.mps else "cpu", "float32")


def probe_device() -> DeviceProbe:
    import torch

    cuda = torch.cuda.is_available()
    return DeviceProbe(cuda, torch.backends.mps.is_available(), cuda and torch.cuda.is_bf16_supported())
