# 🚀 RunPod Deployment Checklist

## ✅ Pre-Deployment Checklist

- [ ] Docker installed locally
- [ ] Docker Hub account created (hub.docker.com)
- [ ] RunPod account created (runpod.io)
- [ ] Added payment method to RunPod ($10-20 for testing)
- [ ] (Optional) OpenAI API key for voice agent

---

## 📋 Step-by-Step Deployment

### **STEP 1: Build Docker Image** (15-20 minutes)

```bash
cd D:\Automationss\runpod
docker build -t neutts-air-gpu:latest .
```

**Expected output:**
- Downloading base image (nvidia/cuda)
- Installing Python packages
- Cloning NeuTTS Air repo
- Downloading models (~2GB)

**If build fails:**
- Check Docker is running
- Check internet connection
- Ensure enough disk space (need ~15GB)

---

### **STEP 2: Push to Docker Hub** (10-15 minutes)

```bash
# Login
docker login
# Username: YOUR_DOCKERHUB_USERNAME
# Password: YOUR_DOCKERHUB_PASSWORD

# Tag the image
docker tag neutts-air-gpu:latest elexizai/agent:latest

# Push
docker push elexizai/agent:latest
```

**Expected output:**
- Pushing layers (8-10 GB total)
- Progress bars showing upload

**If push fails:**
- Check Docker Hub login
- Check image name matches your username
- Check internet connection

---

### **STEP 3: Deploy on RunPod** (5 minutes)

1. Go to: https://www.runpod.io/console/serverless

2. Click **"+ Deploy Endpoint"**

3. **Fill in details:**

   **Endpoint Configuration:**
   ```
   Name: neutts-air-tts
   Container Image: YOUR_DOCKERHUB_USERNAME/neutts-air-gpu:latest
   Container Disk: 20 GB
   ```

   **GPU Configuration:**
   ```
   GPU Type: RTX 4090 (best performance)
   Min Workers: 0 (saves money when idle)
   Max Workers: 5 (auto-scale on demand)
   ```

   **Advanced Settings:**
   ```
   Idle Timeout: 5 seconds
   Execution Timeout: 60 seconds
   FlashBoot: Enabled (faster cold starts)
   ```

4. Click **"Deploy"**

5. Wait 2-3 minutes for initialization

6. **Copy your credentials:**
   - Endpoint ID: (shown in dashboard)
   - API Key: Settings → API Keys → Create New Key

---

### **STEP 4: Test Deployment** (2 minutes)

1. Edit `test_runpod.py`:
   ```python
   RUNPOD_ENDPOINT_ID = "YOUR_ENDPOINT_ID"  # From Step 3
   RUNPOD_API_KEY = "YOUR_API_KEY"          # From Step 3
   ```

2. Run test:
   ```bash
   pip install requests soundfile
   python test_runpod.py
   ```

3. **Expected output:**
   ```
   ✅ SUCCESS!
   Duration: 2.5 seconds
   Text length: 45 characters
   Saved to: test_output_jo.wav
   ```

4. Play the .wav files to verify quality

---

### **STEP 5: Deploy Voice Agent** (Optional)

1. Edit `voice_agent.py`:
   ```python
   RUNPOD_ENDPOINT = "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID"
   RUNPOD_API_KEY = "YOUR_API_KEY"
   OPENAI_API_KEY = "YOUR_OPENAI_KEY"
   ```

2. Install dependencies:
   ```bash
   pip install websockets openai aiohttp
   ```

3. Run server:
   ```bash
   python voice_agent.py
   ```

4. Connect: `ws://localhost:8765`

---

## 🐛 Troubleshooting

### **Docker Build Issues**

**Problem:** "ERROR: Cannot connect to Docker daemon"
```bash
# Solution: Start Docker Desktop
```

**Problem:** "No space left on device"
```bash
# Solution: Clean Docker
docker system prune -a
```

**Problem:** "Package not found" during build
```bash
# Solution: Check internet connection, try again
```

---

### **RunPod Deployment Issues**

**Problem:** "Pod initialization failed"
- Check Container Image name is correct
- Ensure image is public on Docker Hub
- Try reducing Container Disk to 15 GB

**Problem:** "Cold start timeout"
- Increase Execution Timeout to 120 seconds
- Enable FlashBoot in Advanced Settings

**Problem:** "GPU out of memory"
- Switch to smaller model (Q4 → Q2)
- Reduce max workers
- Use GPU with more VRAM (A6000)

---

### **Testing Issues**

**Problem:** "Connection timeout"
- Check endpoint is running (not idle)
- First request takes 3-5 seconds (cold start)
- Subsequent requests are faster

**Problem:** "401 Unauthorized"
- Check API Key is correct
- Ensure "Bearer" prefix in Authorization header

**Problem:** "Audio sounds distorted"
- Check reference voice quality
- Try different voice (jo vs dave)
- Ensure audio file format is WAV

---

## 💰 Cost Breakdown

### **Development Costs:**
- Docker Hub: FREE (for public images)
- Building image: FREE (local compute)

### **RunPod Costs:**

**With RTX 4090 ($0.00045/second):**

| Usage | Time per request | Cost per request | Monthly cost* |
|-------|------------------|------------------|---------------|
| Low (100 req/day) | 1.5s | $0.00068 | ~$2 |
| Medium (500 req/day) | 1.5s | $0.00068 | ~$10 |
| High (2000 req/day) | 1.5s | $0.00068 | ~$40 |

*Assumes min workers = 0 (no idle costs)

**Additional costs:**
- Cold starts: ~3 seconds = $0.00135 per cold start
- Network egress: FREE (included)
- Storage: FREE (container disk included)

---

## 📊 Performance Expectations

### **Cold Start (first request):**
- Time: 3-5 seconds
- Loads model into GPU memory
- Happens after idle timeout

### **Warm Requests (subsequent):**
- Time: 0.5-1.5 seconds per sentence
- Model already in memory
- Instant response

### **Quality:**
- Sample rate: 24 kHz
- Voice cloning: Near-perfect with good reference
- Naturalness: 9/10 (comparable to ElevenLabs)

---

## 🎯 What You Can Do Now

1. **Basic TTS API**: Send text → Get audio
2. **Voice Cloning**: 3 seconds of audio → Clone any voice
3. **Streaming**: Real-time audio generation
4. **Custom Voices**: Upload your own voice samples
5. **Voice Agents**: STT → LLM → TTS pipeline
6. **Scale to Production**: Auto-scales 0-5 workers

---

## 🔥 Quick Start Commands

```bash
# Build & Deploy
cd D:\Automationss\runpod
docker build -t neutts-air-gpu:latest .
docker tag neutts-air-gpu:latest USERNAME/neutts-air-gpu:latest
docker push USERNAME/neutts-air-gpu:latest

# Test
python test_runpod.py

# Voice Agent (optional)
python voice_agent.py
```

---

## 📚 Additional Resources

- RunPod Docs: https://docs.runpod.io/
- NeuTTS Air GitHub: https://github.com/neuphonic/neutts-air
- Docker Hub: https://hub.docker.com/
- Support: RunPod Discord or support@runpod.io

---

## ✅ Final Checklist

Before going to production:

- [ ] Tested all voice types (jo, dave, custom)
- [ ] Tested short and long text (1 word → 500 words)
- [ ] Verified audio quality
- [ ] Set up monitoring (RunPod console)
- [ ] Set up cost alerts (RunPod billing)
- [ ] Documented your API key securely
- [ ] (Optional) Set up custom domain
- [ ] (Optional) Add authentication layer

---

**YOU'RE READY! 🚀**

Any issues? Check the troubleshooting section or the detailed README.md
