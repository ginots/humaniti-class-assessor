# Dependency compatibility investigation

Checked public primary sources on 22 October 2026. This phase installed no packages, downloaded no models, and did not resolve or import the proposed dependency set. These findings establish plausible binary availability, not a working inference environment.

## Interpreter decision

Keep the installed Python 3.14 for the standard-library inventory. For the next phase, first test a separate Python 3.14 environment on E:. There is no evidence-based reason to replace the existing interpreter before testing. If the complete resolver or smoke test exposes a specific blocker, use a side-by-side, regular 64-bit Python 3.13 installation and environment on E:; Python 3.12 is another binary-supported fallback. Do not use a free-threaded interpreter for this deadline-driven prototype.

| Component | Observed public support / files | Implication |
| --- | --- | --- |
| Streamlit | Official installation guide includes 3.14; PyPI 1.66.1 is a universal Python wheel and requires Python >=3.11. | Streamlit itself does not require a downgrade. Its complete dependency set still needs resolution. |
| faster-whisper | 1.2.1 has a universal wheel; upstream requires Python >=3.9. Its dependencies include CTranslate2, PyAV, ONNX Runtime, tokenizers, and Hugging Face Hub. | Check the compiled dependencies, not just faster-whisper's Python version declaration. |
| CTranslate2 | 4.8.3 lists Windows x64 wheels for regular CPython 3.12, 3.13, and 3.14. | A 3.14 Windows binary exists. Version 4.8.3 also includes a CPython 3.14 allocator safety fix. |
| PyAV | 19.0.2 requires Python >=3.12 and provides `cp312-abi3-win_amd64`. | The stable ABI wheel covers regular CPython 3.12+; it bundles FFmpeg libraries, but does not establish that standalone `ffprobe` is installed. |
| ONNX Runtime | 1.31.0 lists Windows x64 wheels for CPython 3.14 and 3.13. | The VAD dependency has a 3.14 Windows binary. |
| tokenizers | 0.23.3 provides `cp310-abi3-win_amd64`. | Its stable ABI wheel covers regular CPython 3.10+. |
| Pydantic | V2 added Python 3.14 support in 2.12. Current pydantic-core 2.50.1 has a CPython 3.14 Windows x64 wheel. | Use Pydantic V2 for result validation; Pydantic V1 is incompatible with Python 3.14. Let Pydantic select its matching core version. |

Sources: [Streamlit installation](https://docs.streamlit.io/get-started/installation/command-line), [Streamlit release files](https://pypi.org/project/streamlit/1.66.1/#files), [faster-whisper release files](https://pypi.org/project/faster-whisper/1.2.1/#files), [faster-whisper dependencies](https://github.com/SYSTRAN/faster-whisper/blob/master/requirements.txt), [CTranslate2 release files](https://pypi.org/project/ctranslate2/4.8.3/#files), [CTranslate2 4.8.3 release](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.8.3), [PyAV release files](https://pypi.org/project/av/19.0.2/#files), [ONNX Runtime release files](https://pypi.org/project/onnxruntime/1.31.0/#files), [tokenizers release files](https://pypi.org/project/tokenizers/0.23.3/#files), [Pydantic releases](https://pypi.org/project/pydantic/), [pydantic-core files](https://pypi.org/project/pydantic_core/2.50.1/#files), [CPython stable ABI](https://docs.python.org/3/c-api/stable.html).

## CPU first; GPU remains unverified

Start the next phase with faster-whisper on CPU using INT8 and a small model, one recording at a time. Benchmark a short, nonconfidential recording before committing to a model size or turnaround promise. Base or small multilingual models are reasonable candidates to compare; their accuracy must be measured for the actual language and audio conditions. Published upstream timings use different hardware and are not predictions for this machine. The 8 GB RAM and 4 GB VRAM budgets favor sequential processing and bounded audio chunks. Avoid adding PyTorch merely to run faster-whisper. [Upstream implementation and benchmarks](https://github.com/SYSTRAN/faster-whisper)

The NVIDIA driver is not the CUDA toolkit or the inference DLLs. Driver 555.97 exceeds NVIDIA's listed Windows minimum 528.33 for CUDA 12.x minor compatibility and 551.78 for the CUDA 12.4 Update 1 toolkit driver. This does not prove that the selected CTranslate2 wheel, GPU, CUDA DLLs, and model execute successfully together. Newer CUDA features can require newer drivers. [NVIDIA CUDA 12.4 release notes](https://docs.nvidia.com/cuda/archive/12.4.1/cuda-toolkit-release-notes/index.html), [minor compatibility caveats](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)

Upstream documentation is inconsistent: faster-whisper's README says CUDA 12 cuBLAS and cuDNN 9, while CTranslate2's installation page still mentions cuDNN 8. CTranslate2's 4.6.3 release explicitly introduced a CUDA convolution implementation that makes cuDNN optional. Therefore, pin and smoke-test the actual CTranslate2 release before choosing any GPU libraries; do not install a guessed CUDA/cuDNN combination. Windows also requires a suitable Visual C++ runtime. GPU setup is optional for the first working prototype. [faster-whisper GPU requirements](https://github.com/SYSTRAN/faster-whisper#gpu), [CTranslate2 installation](https://opennmt.net/CTranslate2/installation.html), [CTranslate2 4.6.3 release](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.6.3)

## Next-phase verification order

Given the 23 October noon IST deadline and 4–5 focused-hour target:

1. Keep caches, environment, models, and temporary audio on E: using the repository environment setup script. Check free space again before downloads.
2. Resolve only prebuilt wheels in a fresh E: environment (`pip install --dry-run --only-binary=:all:` with the chosen packages). This may fetch package metadata; it must never use private recordings. Save the eventual exact versions only after successful resolution.
3. Install that resolved set in the isolated environment; check imports and CPU supported compute types. Do not download model weights implicitly during an import test.
4. Deliberately download one selected model to E:, then run a local, nonconfidential audio smoke test. Validate timestamps and peak memory. For subsequent confidential inference, use explicit local model paths and offline mode.
5. Choose the implementation runtime after those checks, and reproduce it on the eventual host. Any hosting or external processing of confidential material remains contingent on an explicitly permitted service. The final pipeline must generate its own transcript from a new recording; supplied VTTs are development aids only.

No environment, model, complete dependency lock, application, or deployment has been created by this investigation.
