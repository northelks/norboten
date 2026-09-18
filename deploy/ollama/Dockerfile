# syntax=docker/dockerfile:1
# Ollama for a server with no GPU. The official image unpacks to 5 GB, 4.7 of them CUDA, MLX and
# Vulkan libraries a CPU never loads; this is the same release with only the CPU backends kept.
# The archive is streamed and filtered on the way in, so building it needs no room for the rest.
FROM ubuntu:24.04
ARG OLLAMA_VERSION=v0.34.0
ARG TARGETARCH
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl zstd \
    && curl -fsSL "https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-linux-${TARGETARCH}.tar.zst" \
        | zstd -dc \
        | tar -x -C /usr --exclude='lib/ollama/cuda_*' --exclude='lib/ollama/rocm*' \
              --exclude='lib/ollama/vulkan*' --exclude='lib/ollama/mlx*' \
    && apt-get purge -y --auto-remove curl zstd \
    && rm -rf /var/lib/apt/lists/*
ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]
