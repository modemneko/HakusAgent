import asyncio
import threading
import time
from typing import Optional, Callable, Tuple

from .agent import AgentCore
from voice.voice_config import VoiceConfig
from utils.logger import get_logger

logger = get_logger(__name__)

PYAUDIO_AVAILABLE = False
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pass


class VoiceBridge:
    def __init__(self, agent: AgentCore, config: Optional[VoiceConfig] = None):
        self.agent = agent
        self.config = config or VoiceConfig.from_config()
        self.asr = None
        self.tts = None
        self.player = None
        self.recorder = None
        self._running = False
        self._speaking = False
        self._interrupted = False
        self._processing = False
        self._tts_queue = None
        self._event_loop = None

    def init(self, enable_asr: bool = True):
        if enable_asr:
            try:
                from voice.asr_engine import ASREngine
                self.asr = ASREngine(
                    model_name=self.config.asr.model,
                    language=self.config.asr.language
                )
                if not self.asr.is_ready:
                    logger.warning("ASR not ready, voice recognition unavailable")
                    self.asr = None
            except Exception as e:
                logger.error(f"ASR init failed: {e}")
                self.asr = None

        self._init_tts()
        self._init_player()
        logger.info("Voice bridge initialized")

    def init_text_mode(self):
        self._init_tts()
        logger.info("Voice bridge (text mode) initialized")

    def _init_tts(self):
        tts_provider = self.config.tts.provider
        try:
            if tts_provider == "bert-vits2":
                from voice.bert_vits2_tts import BertVITS2TTS
                self.tts = BertVITS2TTS()
                if not self.tts.is_ready:
                    self.tts = self._fallback_tts()
            else:
                self.tts = self._fallback_tts()
        except ImportError:
            logger.warning(f"TTS engine {tts_provider} unavailable, falling back")
            self.tts = self._fallback_tts()

    def _fallback_tts(self):
        try:
            from tts.tts_manager import TTSManager
            manager = TTSManager()
            if manager.is_initialized():
                return manager
            return None
        except Exception as e:
            logger.error(f"TTS fallback failed: {e}")
            return None

    def _init_player(self):
        try:
            from voice.voice_live import AudioPlayer
            self.player = AudioPlayer()
            self.player.init()
        except Exception as e:
            logger.error(f"Audio player init failed: {e}")
            self.player = None

    def start_voice(self):
        if not self.asr or not self.asr.is_ready:
            logger.error("ASR not ready, cannot start voice mode")
            return False

        self._running = True
        self._tts_queue = __import__('queue').Queue()
        self._event_loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(self._event_loop)
            self._event_loop.run_forever()

        self._agent_thread = threading.Thread(target=_run_loop, daemon=True)
        self._agent_thread.start()

        from voice.voice_live import AudioRecorder, VoiceDetector, VoiceSegment
        self.recorder = AudioRecorder(self.config, self._on_speech)
        self.recorder.start()

        tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        tts_thread.start()

        logger.info("Voice mode started")
        return True

    def stop_voice(self):
        self._running = False
        self._interrupted = True
        if self.player:
            self.player.stop()
        if self.recorder:
            self.recorder.stop()
        if hasattr(self, '_event_loop') and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
        logger.info("Voice mode stopped")

    def _on_speech(self, segment):
        if self._processing:
            self._interrupted = True
            if self.player:
                self.player.stop()

        if not self.asr or not self.asr.is_ready:
            return

        text = self.asr.transcribe(segment.audio_path)
        if not text.strip():
            return

        logger.info(f"User: {text}")
        self._speaking = True
        self._interrupted = False
        self._processing = True

        threading.Thread(target=self._process_speech, args=(text,), daemon=True).start()

    def _process_speech(self, text: str):
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.agent.process(text),
                self._event_loop
            )
            response = future.result(timeout=120)

            if response and not self._interrupted:
                logger.info(f"Agent: {response[:100]}...")
                self._tts_queue.put(response)

            self._tts_queue.put(None)
        except Exception as e:
            logger.error(f"Voice processing failed: {e}")
            self._tts_queue.put(None)
        finally:
            self._speaking = False
            self._processing = False

    def _tts_worker(self):
        while self._running:
            try:
                text = self._tts_queue.get(timeout=0.5)
            except Exception:
                continue

            if text is None:
                self._speaking = False
                continue

            if self._interrupted:
                continue

            if self.tts and text:
                try:
                    if hasattr(self.tts, 'generate'):
                        audio_path = self.tts.generate(text)
                    elif hasattr(self.tts, 'generate_audio'):
                        audio_path = self.tts.generate_audio(text)
                    else:
                        audio_path = None

                    if audio_path and not self._interrupted and self.player:
                        done_event = threading.Event()
                        self.player.play_async(audio_path, on_done=done_event.set)
                        done_event.wait(timeout=30)
                except Exception as e:
                    logger.error(f"TTS failed: {e}")

    async def process_text_with_voice(self, text: str) -> Tuple[str, Optional[str]]:
        response = await self.agent.process(text)
        audio_path = None
        if response and self.tts:
            try:
                if hasattr(self.tts, 'generate'):
                    audio_path = await asyncio.get_event_loop().run_in_executor(
                        None, self.tts.generate, response
                    )
            except Exception as e:
                logger.error(f"TTS generation failed: {e}")
        return response, audio_path

    @property
    def is_voice_active(self) -> bool:
        return self._running and self._speaking

    @property
    def is_listening(self) -> bool:
        return self._running and not self._speaking and not self._processing
