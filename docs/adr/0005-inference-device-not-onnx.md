# 0005 — Choose an inference device; defer ONNX Runtime

Status: accepted, 2026-09-17

## Context
The embedding and reranking models refuse to load without a CUDA GPU. Every friend Mentor is going to is on an Apple
Silicon Mac, so as it stands none of them can run it at all.

The desktop brief proposed replacing torch with ONNX Runtime and int8 exports, on the grounds that torch plus CUDA is
about 2 GB and NVIDIA-only. Checking that premise against the packaging indexes: the macOS arm64 torch wheel is about
127 MB, and the CUDA packages that make up the bulk are declared only for Linux. The size argument is a Linux argument.

The performance argument does not survive either, on the machines that matter. ONNX Runtime's CoreML execution
provider documents no support for int8 models, so an int8 export on a Mac most likely runs on the CPU, while torch
with MPS runs on the GPU. A rewrite would have moved the target platform onto its slowest path. The reranker the brief
named for the swap, `mxbai-rerank-xsmall-v2`, does not exist: mixedbread's v2 line is base and large only.

## Decision
Pick the device at load: CUDA, then MPS, then CPU, as a pure function of a probe. Keep torch and sentence-transformers,
keep the models and their dimensions, and keep `mixedbread-ai/mxbai-rerank-base-v2` as the reranker on every device.
Report the chosen device.

ONNX Runtime is deferred, not rejected. Its trigger is a measurement: the first real ingestion on the Windows machine,
which has no MPS and may have no CUDA. If CPU ingestion there is unbearable, ONNX int8 on CPU is the answer, and the
measurement will say how much it is worth.

## Consequences
- Every platform runs. CPU is slow but supported, and slow is a progress bar, where refusing to load is a wall.
- No vectors change. The model, its dimension and its precision on CUDA are untouched, so existing databases stay
  valid and the compatibility test the brief worried about is not needed. A retrieval regression set is still built
  first, because MPS is a different kernel path and ranking can drift silently.
- Precision is bfloat16 on CUDA as today, float32 on MPS and CPU: the Qwen-derived defaults overflow in float16, and
  float32 costs memory a Mac has.
- Out-of-memory handling remains CUDA-specific; elsewhere an allocation failure is an ordinary model failure.
- A known sentence-transformers failure with cross-encoders on MPS is handled by falling the reranker alone back to
  CPU, reported rather than hidden.
- The 2 GB of CUDA packages still install on Linux. That cost is Drew's and nobody else's, and it disappears from
  friends' machines by virtue of the platform markers.
