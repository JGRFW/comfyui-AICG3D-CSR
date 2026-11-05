# Third-Party Notices

## MiniMax H3 Easy 3D latent upscaler

`latent_upscale.py` is adapted from `ComfyUI-MiniMaxH3-Easy`:

- Copyright (c) 2026 nkxx188
- License: MIT
- Source: https://github.com/nkxx188/ComfyUI-MiniMaxH3-Easy

The module is bundled locally so `comfyui-AICG3D-CSR` does not require the original AICG3D or MiniMax H3 Easy plugin to be installed. It is used only for the optional second-pass latent upscale and does not register a public node from this package.

## AICG3D sequence seam repair

`sequence_seam.py` is adapted from the sequence-combine seam repair in `ComfyUI-AICG3D`:

- Copyright (c) nkxx188
- License: MIT
- Source: https://github.com/nkxx188/ComfyUI-AICG3D

The adapted module is used only by `CSR ④` for cross-segment exposure matching, opening low-frequency grade, same-shot motion bridging, hard-cut protection and seam diagnostics. It does not import or register any node from the original plugin.

## License text for the adapted components

The following MIT License text applies to the two adapted components listed above.

Copyright (c) 2026 nkxx188
Copyright (c) nkxx188

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## External runtime components

- ComfyUI is a separate runtime and is not bundled in this repository.
- MiniMax H3 models, text encoders, VAEs, LoRAs, latent upscalers and face detectors are not bundled and are governed by their own licenses.
- FFmpeg and FFprobe are not bundled. Users must comply with the license of the FFmpeg build they install or distribute.
- Python packages such as `numpy` and `filelock` are installed separately and retain their own licenses.
- Optional local vision inference uses the public `llama-cpp-python` chat-handler API. `llama-cpp-python` and its bundled native libraries are not included in this repository and retain their own licenses.

This project is independent and is not affiliated with or endorsed by MiniMax, ComfyUI, Comfy Org, AICG3D, nkxx188, model or LoRA providers, or any referenced platform. Names and trademarks remain the property of their respective owners.

The CSR prompt optimizer is an independent implementation. It does not import or copy the GPL prompt-optimizer implementation from `comfyui-AICG3D`; it communicates with user-selected local OpenAI-compatible endpoints or an optional local GGUF runtime through CSR's own routes.
