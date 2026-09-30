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
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "cli.py"]
