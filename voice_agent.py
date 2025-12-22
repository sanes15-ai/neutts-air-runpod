"""
Real-time Voice Agent using NeuTTS Air + RunPod
================================================
Complete voice agent pipeline: STT -> LLM -> TTS (streaming)

This is similar to Vapi.ai but using your own TTS on RunPod GPU.
"""

import asyncio
import websockets
import json
import base64
import io
import numpy as np
import soundfile as sf
from typing import AsyncIterator

# For STT: Use OpenAI Whisper or Deepgram
import openai  # or use faster-whisper for local STT

# For LLM: Use OpenAI GPT or Groq
from openai import AsyncOpenAI

# For TTS: RunPod endpoint
import requests

class RealtimeVoiceAgent:
    """
    Real-time voice agent with streaming TTS.
    
    Flow:
    1. User speaks -> STT (Whisper)
    2. Text -> LLM (GPT-4)
    3. LLM response -> TTS (NeuTTS Air on RunPod GPU)
    4. Audio -> User (streaming)
    """
    
    def __init__(
        self,
        runpod_endpoint: str,
        runpod_api_key: str,
        openai_api_key: str,
        voice_id: str = "jo"
    ):
        self.runpod_endpoint = runpod_endpoint
        self.runpod_api_key = runpod_api_key
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)
        self.voice_id = voice_id
        
        # Conversation history
        self.conversation_history = [
            {"role": "system", "content": "You are a helpful AI assistant. Keep responses concise and natural for voice conversation."}
        ]
    
    async def speech_to_text(self, audio_data: bytes) -> str:
        """
        Convert speech to text using OpenAI Whisper.
        
        Args:
            audio_data: Audio bytes (WAV format)
        
        Returns:
            Transcribed text
        """
        # Save audio temporarily
        audio_file = io.BytesIO(audio_data)
        audio_file.name = "audio.wav"
        
        # Transcribe with Whisper
        transcript = await self.openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
        
        return transcript.text
    
    async def get_llm_response(self, user_text: str) -> str:
        """
        Get LLM response using GPT-4.
        
        Args:
            user_text: User's text input
        
        Returns:
            LLM response text
        """
        # Add user message to history
        self.conversation_history.append({"role": "user", "content": user_text})
        
        # Get response from GPT-4
        response = await self.openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=self.conversation_history,
            temperature=0.7,
            max_tokens=150  # Keep responses short for voice
        )
        
        assistant_text = response.choices[0].message.content
        
        # Add to history
        self.conversation_history.append({"role": "assistant", "content": assistant_text})
        
        return assistant_text
    
    async def text_to_speech_streaming(self, text: str) -> AsyncIterator[bytes]:
        """
        Convert text to speech using NeuTTS Air on RunPod (streaming).
        
        Args:
            text: Text to convert to speech
        
        Yields:
            Audio chunks (WAV format)
        """
        # Call RunPod endpoint
        headers = {
            "Authorization": f"Bearer {self.runpod_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "input": {
                "text": text,
                "voice_id": self.voice_id,
                "streaming": True
            }
        }
        
        response = requests.post(
            f"{self.runpod_endpoint}/run",
            headers=headers,
            json=payload,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"RunPod API error: {response.text}")
        
        result = response.json()
        
        # Decode base64 audio
        audio_b64 = result["output"]["audio"]
        audio_bytes = base64.b64decode(audio_b64)
        
        # For streaming, we'd need to implement chunked processing
        # For now, return full audio
        yield audio_bytes
    
    async def process_voice_input(self, audio_data: bytes) -> AsyncIterator[bytes]:
        """
        Complete voice agent pipeline.
        
        Args:
            audio_data: User's voice input (WAV bytes)
        
        Yields:
            AI response audio chunks
        """
        print("\n[Agent] Processing voice input...")
        
        # Step 1: Speech to Text
        print("[Agent] 1. Transcribing speech...")
        user_text = await self.speech_to_text(audio_data)
        print(f"[Agent] User said: {user_text}")
        
        # Step 2: Get LLM response
        print("[Agent] 2. Generating response...")
        response_text = await self.get_llm_response(user_text)
        print(f"[Agent] AI response: {response_text}")
        
        # Step 3: Text to Speech (streaming)
        print("[Agent] 3. Converting to speech...")
        async for audio_chunk in self.text_to_speech_streaming(response_text):
            yield audio_chunk
        
        print("[Agent] ✓ Response complete!")
    
    async def websocket_handler(self, websocket):
        """
        WebSocket handler for real-time voice communication.
        
        Client sends: Audio chunks (base64 encoded)
        Server sends: AI response audio chunks (base64 encoded)
        """
        print("[Agent] New client connected")
        
        try:
            async for message in websocket:
                data = json.loads(message)
                
                if data.get("type") == "audio":
                    # Decode audio
                    audio_b64 = data["audio"]
                    audio_bytes = base64.b64decode(audio_b64)
                    
                    # Process and stream response
                    async for response_chunk in self.process_voice_input(audio_bytes):
                        # Send response back
                        response_b64 = base64.b64encode(response_chunk).decode('utf-8')
                        await websocket.send(json.dumps({
                            "type": "audio",
                            "audio": response_b64
                        }))
        
        except websockets.exceptions.ConnectionClosed:
            print("[Agent] Client disconnected")
    
    async def start_server(self, host: str = "0.0.0.0", port: int = 8765):
        """
        Start WebSocket server for voice agent.
        
        Args:
            host: Server host
            port: Server port
        """
        print(f"[Agent] Starting voice agent server on {host}:{port}")
        
        async with websockets.serve(self.websocket_handler, host, port):
            print(f"[Agent] ✓ Voice agent ready! Connect to ws://{host}:{port}")
            await asyncio.Future()  # Run forever


# Example usage
if __name__ == "__main__":
    # Configuration
    RUNPOD_ENDPOINT = "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID"
    RUNPOD_API_KEY = "YOUR_RUNPOD_API_KEY"
    OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
    
    # Create voice agent
    agent = RealtimeVoiceAgent(
        runpod_endpoint=RUNPOD_ENDPOINT,
        runpod_api_key=RUNPOD_API_KEY,
        openai_api_key=OPENAI_API_KEY,
        voice_id="jo"  # or "dave"
    )
    
    # Start server
    asyncio.run(agent.start_server(host="0.0.0.0", port=8765))
