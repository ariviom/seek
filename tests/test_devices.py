from seek.devices import DeviceProbe, DeviceSelection, select_device


def test_device_selection_prefers_cuda_then_mps_then_cpu_with_safe_precision() -> None:
    assert select_device(DeviceProbe(True, True, True)) == DeviceSelection("cuda", "bfloat16")
    assert select_device(DeviceProbe(True, True, False)) == DeviceSelection("cuda", "float32")
    assert select_device(DeviceProbe(False, True, True)) == DeviceSelection("mps", "float32")
    assert select_device(DeviceProbe(False, False, False)) == DeviceSelection("cpu", "float32")
