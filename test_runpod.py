"""
Test RunPod TTS Endpoint
========================
Quick test script after deployment
"""

import requests
import base64
import soundfile as sf
import io

# CONFIGURE YOUR ENDPOINT HERE
RUNPOD_ENDPOINT_ID = "umf1hkbm1kxo7i"  # Your deployed endpoint
RUNPOD_API_KEY = "YOUR_API_KEY"  # Set via environment variable or paste here locally

def test_tts(text: str, voice_id: str = "jo", streaming: bool = False):
    """
    Test the TTS endpoint
    
    Args:
        text: Text to convert to speech
        voice_id: "dave" or "jo"
        streaming: Enable streaming mode
    """
    print(f"\n[Test] Sending request...")
    print(f"  Text: {text[:50]}...")
    print(f"  Voice: {voice_id}")
    print(f"  Streaming: {streaming}")
    
    url = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/run"
    
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "input": {
            "text": text,
            "voice_id": voice_id,
            "streaming": streaming
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        
        if response.status_code != 200:
            print(f"\n❌ Error: {response.status_code}")
            print(response.text)
            return False
        
        result = response.json()
        
        # Check status
        status = result.get("status")
        print(f"\n[Test] Status: {status}")
        
        if status == "COMPLETED":
            output = result.get("output", {})
            
            # Decode audio
            audio_b64 = output.get("audio")
            if not audio_b64:
                print("❌ No audio in response")
                return False
            
            audio_bytes = base64.b64decode(audio_b64)
            audio_array, sr = sf.read(io.BytesIO(audio_bytes))
            
            # Save output
            output_file = f"test_output_{voice_id}.wav"
            sf.write(output_file, audio_array, sr)
            
            # Print stats
            duration = output.get("duration", 0)
            text_length = output.get("text_length", 0)
            
            print(f"\n✅ SUCCESS!")
            print(f"  Duration: {duration:.2f} seconds")
            print(f"  Text length: {text_length} characters")
            print(f"  Sample rate: {sr} Hz")
            print(f"  Audio shape: {audio_array.shape}")
            print(f"  Saved to: {output_file}")
            
            return True
        
        elif status == "IN_PROGRESS":
            print("⏳ Still processing... (try again in a few seconds)")
            return False
        
        else:
            print(f"❌ Unexpected status: {status}")
            print(result)
            return False
    
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        return False

def test_voice_cloning():
    """
    Test custom voice cloning
    (Requires a reference audio file)
    """
    print("\n[Test] Voice Cloning Test")
    print("  Note: You need a reference audio file (3-15 seconds)")
    print("  Skipping for now...")
    # TODO: Implement once you have a reference audio

if __name__ == "__main__":
    print("="*70)
    print("RUNPOD TTS ENDPOINT TEST")
    print("="*70)
    
    # Check configuration
    if RUNPOD_ENDPOINT_ID == "YOUR_ENDPOINT_ID":
        print("\n❌ ERROR: Please configure RUNPOD_ENDPOINT_ID first!")
        print("   Edit this file and replace YOUR_ENDPOINT_ID with your actual endpoint ID")
        exit(1)
    
    if RUNPOD_API_KEY == "YOUR_API_KEY":
        print("\n❌ ERROR: Please configure RUNPOD_API_KEY first!")
        print("   Edit this file and replace YOUR_API_KEY with your actual API key")
        exit(1)
    
    # Test 1: Short text with Jo voice
    print("\n" + "="*70)
    print("TEST 1: Short text (Jo voice)")
    print("="*70)
    test_tts("Hello! I'm your GPU-powered voice assistant.", voice_id="jo")
    
    # Test 2: Short text with Dave voice
    print("\n" + "="*70)
    print("TEST 2: Short text (Dave voice)")
    print("="*70)
    test_tts("Welcome to NeuTTS Air on RunPod. This is amazing!", voice_id="dave")
    
    # Test 3: Longer text
    print("\n" + "="*70)
    print("TEST 3: Longer text")
    print("="*70)
    long_text = """
    NeuTTS Air is a state-of-the-art text to speech model that runs on GPU.
    It can clone any voice with just 3 seconds of audio. 
    This makes it perfect for creating AI voice agents and assistants.
    """
    test_tts(long_text.strip(), voice_id="jo")
    
    # Test 4: Streaming mode
    print("\n" + "="*70)
    print("TEST 4: Streaming mode")
    print("="*70)
    test_tts("This is a streaming test to see real-time generation.", voice_id="jo", streaming=True)
    
    print("\n" + "="*70)
    print("ALL TESTS COMPLETED!")
    print("="*70)
    print("\nCheck the generated .wav files to hear the results.")
