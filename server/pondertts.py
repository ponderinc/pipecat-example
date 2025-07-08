"""Ponder text-to-speech service implementations.

This module provides integration with Ponder's text-to-speech API
supporting WebSocket streaming.
"""

import json
import uuid
from typing import AsyncGenerator, Optional
import websockets
from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    StartFrame,
    StartInterruptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.tts_service import InterruptibleTTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.tracing.service_decorators import traced_tts



class PonderTTSService(InterruptibleTTSService):
    """Ponder WebSocket-based text-to-speech service.

    Provides real-time text-to-speech synthesis using Ponder's WebSocket API.
    Supports streaming audio generation with configurable voice IDs
    """

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str,
        sample_rate: Optional[int] = None,
        **kwargs,
    ):
        """Initialize the Ponder WebSocket TTS service.

        Args:
            api_key: Ponder API key for authentication.
            voice_id: Ponder voice ID for authentication.
            params: Additional input parameters for voice customization.
            **kwargs: Additional arguments passed to parent InterruptibleTTSService.
        """
        super().__init__(
            pause_frame_processing=True,
            sample_rate=sample_rate,
            **kwargs,
        )

        self._api_key = api_key
        self._base_url = "inf.useponder.ai" # <-- can also be your self-hosted Ponder instance
        self._websocket_url = f"wss://{self._base_url}/v1/ws/tts?api_key={api_key}&voice_id={voice_id}"
        self._receive_task = None
        self._request_id = None

        self._settings = {
            "language": "english",
            "output_format": "wav",
            "voice_engine": "Ponder",
            "speed": 1.0,
            "seed": None,
        }
        self.set_model_name("Ponder")
        self.set_voice(voice_id)

    def can_generate_metrics(self) -> bool:
        """Check if this service can generate processing metrics.

        Returns:
            True, as Ponder service supports metrics generation.
        """
        return True

    def language_to_service_language(self, language: Language) -> Optional[str]:
        """Convert a Language enum to Ponder service language format.

        Args:
            language: The language to convert.

        Returns:
            The Ponder-specific language code, or None if not supported.
        """
        return "english"

    async def start(self, frame: StartFrame):
        """Start the Ponder TTS service.

        Args:
            frame: The start frame containing initialization parameters.
        """
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        """Stop the Ponder TTS service.

        Args:
            frame: The end frame.
        """
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        """Cancel the Ponder TTS service.

        Args:
            frame: The cancel frame.
        """
        await super().cancel(frame)
        await self._disconnect()

    async def _connect(self):
        """Connect to Ponder WebSocket and start receive task."""
        await self._connect_websocket()

        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self):
        """Disconnect from Ponder WebSocket and clean up tasks."""
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None

        await self._disconnect_websocket()

    async def _connect_websocket(self):
        """Connect to Ponder websocket."""
        try:
            if self._websocket and self._websocket.open:
                return

            logger.debug("Connecting to Ponder")

            if not self._websocket_url:
                await self._get_websocket_url()

            if not isinstance(self._websocket_url, str):
                raise ValueError("WebSocket URL is not a string")

            self._websocket = await websockets.connect(self._websocket_url)
        except ValueError as e:
            logger.error(f"{self} initialization error: {e}")
            self._websocket = None
            await self._call_event_handler("on_connection_error", f"{e}")
        except Exception as e:
            logger.error(f"{self} initialization error: {e}")
            self._websocket = None
            await self._call_event_handler("on_connection_error", f"{e}")

    async def _disconnect_websocket(self):
        """Disconnect from Ponder websocket."""
        try:
            await self.stop_all_metrics()

            if self._websocket:
                logger.debug("Disconnecting from Ponder")
                await self._websocket.close()
        except Exception as e:
            logger.error(f"{self} error closing websocket: {e}")
        finally:
            self._request_id = None
            self._websocket = None

    def _get_websocket(self):
        """Get the WebSocket connection if available."""
        if self._websocket:
            return self._websocket
        raise Exception("Websocket not connected")

    async def _handle_interruption(self, frame: StartInterruptionFrame, direction: FrameDirection):
        """Handle interruption by stopping metrics and clearing request ID."""
        await super()._handle_interruption(frame, direction)
        await self.stop_all_metrics()
        self._request_id = None

    async def _receive_messages(self):
        """Receive messages from Ponder websocket."""
        async for message in self._get_websocket():
            if isinstance(message, bytes):
                # Skip the WAV header message
                if message.startswith(b"RIFF"):
                    continue
                await self.stop_ttfb_metrics()
                frame = TTSAudioRawFrame(message, self.sample_rate, 1)
                await self.push_frame(frame)
            else:
                logger.debug(f"Received text message: {message}")
                try:
                    msg = json.loads(message)
                    logger.debug(f"Received text message: {msg}")
                    if "error" in msg:
                        logger.error(f"{self} error: {msg}")
                        await self.push_error(ErrorFrame(f"{self} error: {msg['error']}"))
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON message: {message}")

    @traced_tts
    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        """Generate TTS audio from text using Ponder's WebSocket API.

        Args:
            text: The text to synthesize into speech.

        Yields:
            Frame: Audio frames containing the synthesized speech.
        """
        logger.debug(f"{self}: Generating TTS [{text}]")

        try:
            # Reconnect if the websocket is closed
            if not self._websocket or self._websocket.closed:
                await self._connect()

            if not self._request_id:
                await self.start_ttfb_metrics()
                yield TTSStartedFrame()
                self._request_id = str(uuid.uuid4())

            tts_command = {
                "type": "text",
                "text": text,
            }

            try:
                await self._get_websocket().send(json.dumps(tts_command))
                await self.start_tts_usage_metrics(text)
            except Exception as e:
                logger.error(f"{self} error sending message: {e}")
                yield TTSStoppedFrame()
                await self._disconnect()
                await self._connect()
                return

            # The actual audio frames will be handled in _receive_task_handler
            yield None

        except Exception as e:
            logger.error(f"{self} error generating TTS: {e}")
            yield ErrorFrame(f"{self} error: {str(e)}")