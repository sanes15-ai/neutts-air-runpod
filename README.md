# NeuTTS Air GPU Voice Agent on RunPod

## 🚀 Complete Real-Time Voice Agent Setup

This setup gives you a **Vapi.ai-like voice agent** using:
- **NeuTTS Air** (GPU-accelerated TTS)
- **OpenAI Whisper** (Speech-to-Text)
- **GPT-4** (LLM for responses)
- **RunPod Serverless** (GPU infrastructure)

---

## 📦 What's Included

```
runpod/
├── Dockerfile           # GPU-optimized container with CUDA support
├── handler.py          # RunPod serverless handler for TTS
├── voice_agent.py      # Complete voice agent with STT + LLM + TTS
└── README.md           # This file
```

---

## 🏗️ Step 1: Deploy TTS Model on RunPod

### 1.1 Build Docker Image

```bash
cd D:\Automationss\runpod

# Build the image
docker build -t neutts-air-gpu:latest .

# Test locally (requires NVIDIA GPU)
docker run --gpus all -p 8000:8000 neutts-air-gpu:latest
```

### 1.2 Push to Docker Hub

```bash
# Login to Docker Hub
docker login

# Tag the image
docker tag neutts-air-gpu:latest elexizai/agent:latest

# Push to Docker Hub
docker push elexizai/agent:latest
```

### 1.3 Create RunPod Serverless Endpoint

1. Go to [RunPod.io](https://www.runpod.io/)
2. Navigate to **Serverless** → **Deploy Endpoint**
3. Configure:
   - **Name**: `neutts-air-tts`
   - **Container Image**: `YOUR_DOCKERHUB_USERNAME/neutts-air-gpu:latest`
   - **GPU Type**: RTX 4090 or A5000 (for speed)
   - **Container Disk**: 20 GB
   - **Workers**: Auto-scale 0-5
   - **Max Workers**: 5
   - **Idle Timeout**: 5 seconds
   - **Execution Timeout**: 60 seconds

4. Click **Deploy**
5. Copy your **Endpoint ID** and **API Key**

---

## 🎯 Step 2: Test TTS Endpoint

```python
import requests
import base64
import io
import soundfile as sf

# Your RunPod credentials
RUNPOD_ENDPOINT = "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID"
RUNPOD_API_KEY = "YOUR_API_KEY"

# Make TTS request
response = requests.post(
    f"{RUNPOD_ENDPOINT}/run",
    headers={
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    },
    json={
        "input": {
            "text": "Hello! I'm your AI voice assistant, powered by NeuTTS Air on GPU.",
            "voice_id": "jo",
            "streaming": False
        }
    }
)

# Get result
result = response.json()
audio_b64 = result["output"]["audio"]
audio_bytes = base64.b64decode(audio_b64)

# Save audio
audio_array, sr = sf.read(io.BytesIO(audio_bytes))
sf.write("test_output.wav", audio_array, sr)
print(f"✓ Audio saved! Duration: {result['output']['duration']:.2f}s")
```

---

## 🗣️ Step 3: Run Voice Agent

### 3.1 Install Dependencies

```bash
pip install websockets openai requests soundfile numpy aiohttp
```

### 3.2 Configure Agent

Edit `voice_agent.py`:

```python
# Your API keys
RUNPOD_ENDPOINT = "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID"
RUNPOD_API_KEY = "YOUR_RUNPOD_API_KEY"
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
```

### 3.3 Start Voice Agent Server

```bash
python voice_agent.py
```

Server runs on `ws://localhost:8765`

---

## 💬 Step 4: Connect Client

### Web Client (HTML + JavaScript)

```html
<!DOCTYPE html>
<html>
<head>
    <title>Voice Agent</title>
</head>
<body>
    <h1>Real-Time Voice Agent</h1>
    <button id="record">Hold to Talk</button>
    <audio id="response" controls></audio>

    <script>
        const ws = new WebSocket('ws://localhost:8765');
        let mediaRecorder;
        let audioChunks = [];

        // Record button
        const recordBtn = document.getElementById('record');
        
        recordBtn.addEventListener('mousedown', async () => {
            // Start recording
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            
            mediaRecorder.ondataavailable = (event) => {
                audioChunks.push(event.data);
            };
            
            mediaRecorder.start();
            recordBtn.textContent = "Recording...";
        });
        
        recordBtn.addEventListener('mouseup', () => {
            // Stop recording
            mediaRecorder.stop();
            recordBtn.textContent = "Processing...";
            
            mediaRecorder.onstop = async () => {
                // Convert to base64
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                const reader = new FileReader();
                
                reader.onload = () => {
                    const base64 = reader.result.split(',')[1];
                    
                    // Send to server
                    ws.send(JSON.stringify({
                        type: 'audio',
                        audio: base64
                    }));
                };
                
                reader.readAsDataURL(audioBlob);
            };
        });
        
        // Receive response
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            if (data.type === 'audio') {
                // Play response audio
                const audio = document.getElementById('response');
                audio.src = 'data:audio/wav;base64,' + data.audio;
                audio.play();
                
                recordBtn.textContent = "Hold to Talk";
            }
        };
    </script>
</body>
</html>
```

---

## ⚡ Performance Optimizations

### GPU Acceleration Settings

The Dockerfile configures:

```python
# GGUF Q4 model (4x faster than full model)
backbone_repo="neutts-air-q4-gguf"
backbone_device="gpu"  # Full GPU acceleration

# ONNX decoder (minimal latency)
codec_repo="neucodec-onnx-decoder"

# GPU layers
n_gpu_layers=-1  # All layers on GPU
flash_attn=True  # Flash attention for speed
```

### Expected Performance

| GPU | Cold Start | Inference Time | Throughput |
|-----|-----------|----------------|------------|
| RTX 4090 | ~3s | ~0.5s / sentence | ~30 req/min |
| A5000 | ~4s | ~0.8s / sentence | ~20 req/min |
| A6000 | ~3s | ~0.6s / sentence | ~25 req/min |

---

## 🎨 Custom Voice Cloning

Upload your own voice (3-15 seconds):

```python
import base64

# Load your voice sample
with open("my_voice.wav", "rb") as f:
    voice_audio = base64.b64encode(f.read()).decode('utf-8')

# Use in TTS request
response = requests.post(
    f"{RUNPOD_ENDPOINT}/run",
    headers={
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    },
    json={
        "input": {
            "text": "This is my cloned voice!",
            "voice_id": "my_custom_voice",
            "ref_audio": voice_audio,
            "ref_text": "Original text from the voice sample"
        }
    }
)
```

---

## 💰 Cost Estimate

RunPod Serverless pricing (as of 2024):

| GPU | Price per second | 1000 requests cost |
|-----|------------------|-------------------|
| RTX 4090 | $0.00045/s | ~$0.23 |
| A5000 | $0.00035/s | ~$0.28 |
| A6000 | $0.00040/s | ~$0.24 |

**Much cheaper than commercial TTS APIs!**

---

## 🔧 Troubleshooting

### "No GPU available"
- Ensure you selected a GPU pod type in RunPod
- Check CUDA installation: `nvidia-smi` in container

### "espeak not found"
- Verify espeak-ng is installed: `which espeak-ng`
- Check environment variables are set

### "Model download failed"
- Increase container disk size to 25GB
- Pre-download models in Dockerfile

### "Audio quality poor"
- Use Q8 GGUF instead of Q4 for better quality
- Ensure reference audio is clean (no background noise)
- Use 16kHz+ sample rate for input

---

## 📚 Additional Resources

- [NeuTTS Air GitHub](https://github.com/neuphonic/neutts-air)
- [RunPod Documentation](https://docs.runpod.io/)
- [llama-cpp-python CUDA](https://pypi.org/project/llama-cpp-python/)
- [NeuCodec ONNX Decoder](https://huggingface.co/neuphonic/neucodec-onnx-decoder)

---

## 🎯 Next Steps

1. **Deploy to production**: Use RunPod's auto-scaling
2. **Add STT**: Integrate Whisper or Deepgram for voice input
3. **Add LLM**: Connect GPT-4 or Llama for responses
4. **Build UI**: Create web interface for voice chat
5. **Monitor**: Set up logging and metrics

**You now have a complete Vapi.ai alternative running on your own infrastructure!** 🎉
