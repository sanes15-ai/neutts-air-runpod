"""
RunPod Serverless Handler for NeuTTS Air GPU Voice Agent
=========================================================
Real-time TTS with GPU acceleration and streaming support.
"""

import runpod
import sys
import os
import base64
import io
import numpy as np
import soundfile as sf
import torch

sys.path.insert(0, '/app/neutts-air')
from neuttsair.neutts import NeuTTSAir

# Global TTS instance (loaded once)
tts = None
ref_codes_cache = {}

def load_tts_model():
    """Load NeuTTS Air model with GPU acceleration"""
    global tts
    
    try:
        print("Loading NeuTTS Air with GPU acceleration...")
        
        # Check if models are local files or HF repos
        backbone_path = "/models/neutts-air-q4-gguf"
        if not os.path.exists(backbone_path):
            backbone_path = "neuphonic/neutts-air-q4-gguf"  # Fallback to HF
        
        codec_path = "/models/neucodec-onnx-decoder"
        if not os.path.exists(codec_path):
            codec_path = "neuphonic/neucodec-onnx-decoder"  # Fallback to HF
        
        tts = NeuTTSAir(
            backbone_repo=backbone_path,  # Local or HF
            backbone_device="gpu",  # GPU acceleration
            codec_repo=codec_path,  # Local or HF
            codec_device="cpu"  # ONNX only runs on CPU
        )
        
        print("✓ NeuTTS Air loaded successfully on GPU!")
        return tts
    
    except Exception as e:
        print(f"❌ ERROR loading TTS model: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

def encode_reference_voice(ref_audio_base64: str, voice_id: str):
    """
    Encode reference voice and cache it.
    
    Args:
        ref_audio_base64: Base64 encoded WAV audio (3-15 seconds)
        voice_id: Unique identifier for this voice
    
    Returns:
        ref_codes: Encoded reference codes
    """
    global ref_codes_cache
    
    if voice_id in ref_codes_cache:
        return ref_codes_cache[voice_id]
    
    # Decode base64 audio
    audio_bytes = base64.b64decode(ref_audio_base64)
    audio_array, sr = sf.read(io.BytesIO(audio_bytes))
    
    # Save temporarily
    temp_path = f"/tmp/{voice_id}.wav"
    sf.write(temp_path, audio_array, sr)
    
    # Encode with NeuTTS
    ref_codes = tts.encode_reference(temp_path)
    
    # Cache for future use
    ref_codes_cache[voice_id] = ref_codes
    
    # Cleanup
    os.remove(temp_path)
    
    return ref_codes

def handler(job):
    """
    RunPod handler for TTS inference.
    
    Input format:
    {
        "text": "Text to convert to speech",
        "voice_id": "dave",  # or custom voice
        "ref_audio": "base64_encoded_wav",  # Optional: for custom voice cloning
        "ref_text": "Reference text for the audio",
        "streaming": false  # true for streaming mode
    }
    
    Output format:
    {
        "audio": "base64_encoded_wav",
        "duration": 2.5,
        "sample_rate": 24000
    }
    """
    global tts
    
    job_input = job["input"]
    
    # Get input parameters
    text = job_input.get("text")
    voice_id = job_input.get("voice_id", "dave")
    ref_audio_b64 = job_input.get("ref_audio")
    ref_text = job_input.get("ref_text", "")
    streaming = job_input.get("streaming", False)
    
    if not text:
        return {"error": "No text provided"}
    
    # Load model if not loaded
    if tts is None:
        load_tts_model()
    
    # Handle reference voice
    if ref_audio_b64:
        # Custom voice cloning
        ref_codes = encode_reference_voice(ref_audio_b64, voice_id)
    else:
        # Use default voices
        default_voices = {
            "dave": "/app/neutts-air/samples/dave.wav",
            "jo": "/app/neutts-air/samples/jo.wav"
        }
        
        if voice_id not in default_voices:
            return {"error": f"Unknown voice_id: {voice_id}"}
        
        ref_audio_path = default_voices[voice_id]
        
        # Load reference text
        ref_text_path = ref_audio_path.replace(".wav", ".txt")
        with open(ref_text_path, 'r') as f:
            ref_text = f.read().strip()
        
        # Encode reference
        if voice_id not in ref_codes_cache:
            ref_codes_cache[voice_id] = tts.encode_reference(ref_audio_path)
        
        ref_codes = ref_codes_cache[voice_id]
    
    # Generate speech
    if streaming:
        # Streaming mode (for real-time agents)
        audio_chunks = []
        for chunk in tts.infer_stream(text, ref_codes, ref_text):
            audio_chunks.append(chunk)
        
        # Concatenate all chunks
        wav = np.concatenate(audio_chunks)
    else:
        # Standard inference
        wav = tts.infer(text, ref_codes, ref_text)
    
    # Convert to base64
    audio_buffer = io.BytesIO()
    sf.write(audio_buffer, wav, 24000, format='WAV')
    audio_buffer.seek(0)
    audio_b64 = base64.b64encode(audio_buffer.read()).decode('utf-8')
    
    duration = len(wav) / 24000
    
    return {
        "audio": audio_b64,
        "duration": duration,
        "sample_rate": 24000,
        "text_length": len(text),
        "voice_id": voice_id
    }

# Start RunPod serverless worker
runpod.serverless.start({"handler": handler})
