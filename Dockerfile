# -- 1. BASE -------------------------------------------------------------------
FROM nvidia/cuda:12.1.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV CUDA_HOME=/usr/local/cuda-12.1
ENV FORCE_CUDA=1
ENV TORCH_CUDA_ARCH_LIST="8.0 8.6 8.9 9.0+PTX"
ENV PYOPENGL_PLATFORM=egl
ENV EGL_PLATFORM=device
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
ENV HF_HOME=/app/.cache/huggingface
WORKDIR /app

RUN apt-get update && apt-get install -y \
    software-properties-common wget git build-essential \
    libgl1-mesa-glx libglib2.0-0 \
    libegl1 libopengl0 libegl-mesa0 libosmesa6 libgles2 libgl1-mesa-dri \
    && add-apt-repository ppa:deadsnakes/ppa -y && apt-get update \
    && apt-get install -y python3.7 python3.7-venv python3.7-dev \
    && apt-get install -y python3.10 python3.10-venv python3.10-dev \
    && rm -rf /var/lib/apt/lists/*

# -- 2. RESTORMER (Python 3.7) -------------------------------------------------
RUN python3.7 -m venv /opt/venv_restormer
RUN /opt/venv_restormer/bin/pip install --upgrade pip setuptools wheel && \
    /opt/venv_restormer/bin/pip install torch==1.13.1+cu117 torchvision==0.14.1+cu117 \
        --extra-index-url https://download.pytorch.org/whl/cu117 && \
    /opt/venv_restormer/bin/pip install \
        matplotlib scikit-learn scikit-image opencv-python \
        yacs joblib natsort h5py tqdm einops gdown addict future \
        lmdb numpy pyyaml requests scipy yapf lpips

RUN git clone https://github.com/swz30/Restormer.git /app/Restormer && \
    cd /app/Restormer && /opt/venv_restormer/bin/python setup.py develop --no_cuda_ext

RUN /opt/venv_restormer/bin/python -c "\
import os, subprocess; \
models = { \
    'Defocus_Deblurring': '1bRBG8DG_72AGA6-eRePvChlT5ZO4cwJ4', \
    'Denoising':          '1Qwsjyny54RZWa7zC4Apg7exixLBo4uF0', \
    'Deraining':          '1ZEDDEVW0UgkpWi-N4Lj_JUoVChGXCu_u', \
    'Motion_Deblurring':  '1czMyfRTQDX3j3ErByYeZ1PM4GVLbJeGK', \
}; \
[ (os.makedirs(os.path.join('/app/Restormer', k, 'pretrained_models'), exist_ok=True), \
   subprocess.run(['/opt/venv_restormer/bin/gdown', '--folder', '--id', v, \
                   '-O', os.path.join('/app/Restormer', k, 'pretrained_models'), '--fuzzy'])) \
  for k, v in models.items() ]"

# -- 3. WONDER3D (Python 3.10) -------------------------------------------------
RUN python3.10 -m venv /opt/venv_wonder3d

RUN /opt/venv_wonder3d/bin/pip install --upgrade pip && \
    /opt/venv_wonder3d/bin/pip install \
        torch==2.4.1 torchvision==0.19.1 torchaudio \
        --index-url https://download.pytorch.org/whl/cu121

RUN /opt/venv_wonder3d/bin/pip install \
    https://github.com/MiroPsota/torch_packages_builder/releases/download/pytorch3d-0.7.9/pytorch3d-0.7.9+pt2.4.1cu121-cp310-cp310-linux_x86_64.whl

RUN /opt/venv_wonder3d/bin/pip install ninja setuptools wheel packaging

# RUN /opt/venv_wonder3d/bin/pip install \
#     git+https://github.com/NVlabs/nvdiffrast.git --no-build-isolation

RUN git clone https://github.com/NVlabs/nvdiffrast.git /tmp/nvdiffrast && \
    cd /tmp/nvdiffrast && \
    CUDA_HOME=/usr/local/cuda-12.1 \
    /opt/venv_wonder3d/bin/pip install . --no-build-isolation && \
    cd /app && \
    /opt/venv_wonder3d/bin/python -c "import nvdiffrast.torch as dr; print('nvdiffrast installed successfully!')"

RUN /opt/venv_wonder3d/bin/pip install \
    torch-scatter -f https://data.pyg.org/whl/torch-2.4.1+cu121.html

RUN /opt/venv_wonder3d/bin/pip install \
    pymeshlab \
    trimesh \
    google-cloud-storage

RUN git clone https://github.com/xxlong0/Wonder3D.git /app/Wonder3D && \
    cd /app/Wonder3D && git checkout Wonder3D_Plus && \
    grep -vE "pytorch3d|nvdiffrast|torch-scatter" requirements.txt > req_docker.txt && \
    /opt/venv_wonder3d/bin/pip install -r req_docker.txt && \
    find . -name "requirements.txt" -not -path "./requirements.txt" \
        -exec /opt/venv_wonder3d/bin/pip install -r {} + && \
    /opt/venv_wonder3d/bin/pip install \
        transformers==4.40.0 huggingface-hub==0.36.2 "numpy<2.0" rembg

RUN /opt/venv_wonder3d/bin/python -c "\
from huggingface_hub import snapshot_download; import os, subprocess; \
snapshot_download(repo_id='flamehaze1115/Wonder3D_plus', local_dir='/app/Wonder3D/ckpts', \
                  local_dir_use_symlinks=False); \
os.makedirs('/app/Wonder3D/sam_pt', exist_ok=True); \
subprocess.run(['wget', 'https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth', \
                '-O', '/app/Wonder3D/sam_pt/sam_vit_h_4b8939.pth'])"

# -- 4. PROJECT FILES ----------------------------------------------------------
COPY assets/optimize_mesh.py          /app/utils/optimize_mesh.py

# Both Wonder3D runners — chosen at runtime via --wonder3d_mode arg
COPY assets/run_wonder3d_float16.py   /app/Wonder3D/run_colab_float16.py
# Official run.py already exists in the cloned repo at /app/Wonder3D/run_colab.py
# We copy it explicitly to guarantee the version we want
COPY assets/run_wonder3d_official.py  /app/Wonder3D/run_colab_official.py

COPY cloud/cloud_pipeline.py          /app/cloud_pipeline.py

# -- 5. ENTRYPOINT -------------------------------------------------------------
ENTRYPOINT ["/opt/venv_wonder3d/bin/python", "/app/cloud_pipeline.py"]
CMD ["--input_image", "gs://default-bucket/input.png"]