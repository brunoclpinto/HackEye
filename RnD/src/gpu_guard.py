"""GPU is required, never optional. No function in this module has a CPU
fallback path — every caller is expected to exit hard on failure.

ONNX Runtime in particular will silently fall back to CPU if the CUDA
execution provider fails to load, and the only symptom is frames taking much
longer than expected. assert_onnxruntime_cuda() exists specifically to turn
that silent failure into a loud one.
"""

import sys

import torch


def assert_torch_cuda() -> torch.device:
    """Exit the process if CUDA is unavailable. Returns the device to use."""
    if not torch.cuda.is_available():
        _fail(
            "CUDA is not available to PyTorch inside this container.\n"
            "This rig has no CPU fallback by design (see RnD/src/gpu_guard.py).\n"
            "Check: `docker compose run --rm rnd nvidia-smi`, and that the\n"
            "`nvidia` container runtime is selected (see RnD/compose.yaml)."
        )

    name = torch.cuda.get_device_name(0)
    capability = torch.cuda.get_device_capability(0)
    print(f"[gpu_guard] CUDA device: {name}, compute capability {capability}", file=sys.stderr)

    if capability < (7, 0):
        _fail(
            f"CUDA device capability {capability} looks too old for this pipeline. "
            "Refusing to continue rather than run inference at a crawl."
        )

    return torch.device("cuda:0")


def assert_onnxruntime_cuda(session) -> None:
    """Verify an onnxruntime.InferenceSession is actually using CUDA.

    ONNXRuntime does not raise when CUDAExecutionProvider fails to load — it
    just falls back to CPUExecutionProvider. `providers=[...]` on session
    creation is a *request*, not a guarantee. This checks what was actually
    granted.
    """
    active = session.get_providers()
    if "CUDAExecutionProvider" not in active:
        _fail(
            f"onnxruntime session is NOT using CUDA (active providers: {active}). "
            "It silently fell back to CPU. Check the onnxruntime-gpu install "
            "and CUDA/cuDNN versions inside the container."
        )
    print(f"[gpu_guard] onnxruntime providers: {active}", file=sys.stderr)


def _fail(message: str) -> None:
    print(f"[gpu_guard] FATAL: {message}", file=sys.stderr)
    sys.exit(1)
