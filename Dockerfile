# RunPod NeuTTS Air GPU Voice Agent
# Real-time TTS with GPU acceleration
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$CUDA_HOME/bin:$PATH

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    espeak-ng \
    libespeak-ng1 \
    git \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set espeak environment variables
ENV PHONEMIZER_ESPEAK_LIBRARY=/usr/lib/x86_64-linux-gnu/libespeak-ng.so.1
ENV PHONEMIZER_ESPEAK_PATH=/usr/bin/espeak-ng

# Upgrade pip
RUN pip3 install --upgrade pip

# Install build tools needed for llama-cpp-python
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# Install llama-cpp-python with CUDA support (GPU acceleration)
# Using GGML_CUDA (new flag, LLAMA_CUBLAS is deprecated)
RUN CMAKE_ARGS="-DGGML_CUDA=on" pip3 install llama-cpp-python --force-reinstall --no-cache-dir

# Install PyTorch with CUDA (separate step for caching)
RUN pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install core dependencies (separate step for caching)
RUN pip3 install phonemizer librosa soundfile numpy scipy

# Install neucodec and perth FIRST (they bring their own transformers)
RUN pip3 install perth neucodec onnxruntime-gpu

# FORCE reinstall transformers AFTER neucodec to ensure HubertModel is available
# neucodec requires HubertModel which needs transformers>=4.28
RUN pip3 install --force-reinstall --no-cache-dir "transformers==4.36.2"

# Install web/API packages (separate step for caching)
RUN pip3 install fastapi uvicorn websockets aiohttp

# Install HuggingFace and RunPod BEFORE downloading models (CRITICAL FIX)
RUN pip3 install huggingface_hub runpod

# Install audio package (can fail sometimes, separate)
RUN pip3 install pyaudio || echo "pyaudio install failed, continuing..."

# Clone NeuTTS Air repo
WORKDIR /app
RUN git clone https://github.com/neuphonic/neutts-air.git
WORKDIR /app/neutts-air

# Verify NeuTTS Air structure (NEW)
RUN ls -la /app/neutts-air/ && echo "✓ NeuTTS Air cloned successfully"

# Pre-download models to /models directory
RUN mkdir -p /models
RUN python3 -c "from huggingface_hub import snapshot_download; snapshot_download('neuphonic/neutts-air-q4-gguf', local_dir='/models/neutts-air-q4-gguf', local_dir_use_symlinks=False)"
RUN python3 -c "from huggingface_hub import snapshot_download; snapshot_download('neuphonic/neucodec-onnx-decoder', local_dir='/models/neucodec-onnx-decoder', local_dir_use_symlinks=False)"

# Verify models downloaded successfully (NEW)
RUN ls -la /models/ && echo "✓ Models downloaded successfully"

# Copy application code
COPY handler.py /app/handler.py
COPY voice_agent.py /app/voice_agent.py

# Expose port for API
EXPOSE 8000

# RunPod handler
CMD ["python3", "/app/handler.py"]
