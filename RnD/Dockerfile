# GPU-only R&D rig for HackEye. No CPU fallback is provided anywhere in this
# image on purpose — see gpu_guard.py. If CUDA isn't available in the
# container, the pipeline refuses to start rather than silently running slow.
#
# Blackwell (RTX 50-series, sm_120) needs CUDA 12.8+. This base image ships it.
FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime

WORKDIR /rnd

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Depth Anything 3 (Apache-2.0), pinned to a commit. --no-deps: its metadata demands numpy<2,
# xformers, open3d, evo, pycolmap, ... that monocular inference never touches; the imports it
# does need are in requirements.txt. The release zip has no git metadata, so give hatch-vcs a version.
ARG DA3_COMMIT=3d835ec1a5802d64a8b8b15f817a1ab54809bfe4
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 pip install --no-cache-dir --no-deps \
    https://github.com/ByteDance-Seed/Depth-Anything-3/archive/${DA3_COMMIT}.zip

COPY . .

ENTRYPOINT ["python", "cli.py"]
