# Image Cicero + bot de dialogue, reconstruite entièrement depuis les sources.
#
# Contexte de build : l'arbre amont/cicero préparé par install.sh (amont cloné
# au commit épinglé, sous-modules récupérés, patchs et fichiers du dépôt appliqués).
#
# ÉTAT : build complet validé le 2026-10-03 (voir README, « État »).
# La recette transcrit pas à pas la compilation qui a réussi hors Docker sur
# Ubuntu 26.04 : gcc-11, conda python 3.7, PyTorch 1.7.1 / cudatoolkit 11.0,
# protobuf 3.19.1, compilation en -j1 (la compilation parallèle a fait tomber
# la machine par manque de mémoire).
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

# nvidia-cuda-toolkit : la configuration CMake de PyTorch (Caffe2Config) exige nvcc et
# les en-têtes CUDA à la compilation de postman et de dipcc, même si l'exécution
# n'utilise que le cudatoolkit de conda.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget bzip2 gnupg git \
    build-essential gcc-11 g++-11 autoconf libtool pkg-config \
    libgoogle-glog-dev libgflags-dev libunwind-dev \
    nvidia-cuda-toolkit \
    && rm -rf /var/lib/apt/lists/*

# Node.js + CLI Claude Code (dialogue en mode headless, authentifié par abonnement)
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code

# Conda (Miniforge : pas de conditions d'utilisation à accepter en mode non interactif)
ENV CONDA_DIR=/opt/conda
RUN wget -q https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh \
    && bash /tmp/miniforge.sh -b -p ${CONDA_DIR} && rm /tmp/miniforge.sh

ENV CONDA_PREFIX=${CONDA_DIR}/envs/diplomacy_cicero
# mkl et intel-openmp épinglés : d'un build à l'autre, conda a résolu mkl 2021.4 ou 2025.0 ;
# avec le second, `import torch` échoue (symbole iJIT_IsProfilingActive manquant).
RUN ${CONDA_DIR}/bin/conda create -y -n diplomacy_cicero -c conda-forge python=3.7 \
    && ${CONDA_DIR}/bin/conda install -y -n diplomacy_cicero -c pytorch -c defaults -c conda-forge \
       pytorch=1.7.1 torchvision=0.8.2 cudatoolkit=11.0 cudnn=8.0 pybind11=2.10.1 go cmake=3.27 libprotobuf=3.19.1 \
       mkl=2021.4.0 intel-openmp=2021.4.0 \
    && ${CONDA_DIR}/bin/conda clean -afy

ENV PATH="${CONDA_PREFIX}/bin:${PATH}"
ENV CC=gcc-11 CXX=g++-11
ENV CUDNN_LIBRARY_PATH="${CONDA_PREFIX}/lib" CUDNN_INCLUDE_PATH="${CONDA_PREFIX}/include"
ENV LD_LIBRARY_PATH="${CONDA_PREFIX}/lib" CMAKE_PREFIX_PATH="${CONDA_PREFIX}"
ENV N_DIPCC_JOBS=1

WORKDIR /opt/cicero
COPY . /opt/cicero

# Ordre repris de l'installation qui a réussi.
RUN pip install -r requirements.txt
RUN pip install -e ./thirdparty/github/fairinternal/postman/nest/
RUN pip install -e ./thirdparty/github/fairinternal/postman/postman/
# protobuf 3.19.1 et mypy-protobuf 2.10 strictement : le correctif de protos d'amont en dépend.
RUN pip install "protobuf==3.19.1" "types-protobuf==3.19.22" --no-deps \
    && pip install "mypy-protobuf==2.10" --no-deps --force-reinstall
RUN pip install -e . --no-build-isolation
RUN pip install -r fairdiplomacy_external/requirements.txt --no-build-isolation
RUN make -j1

RUN mkdir -p /opt/claude_dialogue_workdir && chmod +x docker-entrypoint.sh check_orders.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
