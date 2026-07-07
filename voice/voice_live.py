import asyncio
import threading
import time
import os
import re
import wave
import numpy as np
from typing import Optional, Callable, Tuple
from dataclasses import dataclass
from queue import Queue, Empty

from .voice_config import VoiceConfig
from utils.logger import get_logger

try:
    from hakus.protocol import (
        TextDelta,
        TurnCompleted,
        TurnFailed,
        Cancelled as CancelledEvent,
    )
except ImportError:
    TextDelta = None
    TurnCompleted = None
    TurnFailed = None
    CancelledEvent = None

logger = get_logger(__name__)

PYAUDIO_AVAILABLE = False
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pass


@dataclass
class VoiceSegment:
    audio_data: bytes
    timestamp: float
    duration: float
    audio_path: str = ""


class VoiceDetector:
    def __init__(self, sample_rate: int = 16000, threshold: int = 600, min_duration: float = 0.3):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_duration = min_duration

    def is_voice(self, audio_data: bytes) -> bool:
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            return np.max(np.abs(audio_array)) > self.threshold
        except Exception:
            return False


class AudioRecorder:
    def __init__(self, config: VoiceConfig, on_speech: Callable[[VoiceSegment], None]):
        self.config = config
        self.on_speech = on_speech
        self.sample_rate = config.asr.sample_rate
        self.channels = 1
        self.chunk = 1024
        self.detector = VoiceDetector(
            self.sample_rate,
            config.asr.threshold,
            config.asr.min_duration
        )

        self._running = False
        self._stream = None
        self._pyaudio = None
        self._buffer = []
        self._last_voice_time = 0
        self._silence_timeout = config.asr.silence_timeout
        self._paused = False

    def start(self):
        if not PYAUDIO_AVAILABLE:
            raise ImportError("PyAudio 未安装，请运行: pip install pyaudio")

        self._running = True
        self._pyaudio = pyaudio.PyAudio()
        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk
        )

        thread = threading.Thread(target=self._record_loop, daemon=True)
        thread.start()
        logger.info("🎤 麦克风录音已启动")

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pyaudio:
            self._pyaudio.terminate()
        logger.info("麦克风录音已停止")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False
        self._buffer.clear()

    def _record_loop(self):
        audio_buffer = []

        while self._running:
            try:
                data = self._stream.read(self.chunk, exception_on_overflow=False)
            except Exception:
                continue

            if self._paused:
                continue

            audio_buffer.append(data)

            buffer_duration = len(audio_buffer) * self.chunk / self.sample_rate

            if buffer_duration >= 0.5:
                raw_audio = b''.join(audio_buffer)

                if self.detector.is_voice(raw_audio):
                    self._last_voice_time = time.time()
                    self._buffer.append((raw_audio, time.time()))
                else:
                    if self._buffer and (time.time() - self._last_voice_time) > self._silence_timeout:
                        self._save_and_emit()

                audio_buffer = []

    def _save_and_emit(self):
        if not self._buffer:
            return

        audio_frames = [seg[0] for seg in self._buffer]
        duration = sum(len(f) for f in audio_frames) / self.sample_rate / 2

        output_dir = self.config.tts.output_dir
        os.makedirs(output_dir, exist_ok=True)
        audio_path = f"{output_dir}/speech_{int(time.time() * 1000)}.wav"

        try:
            with wave.open(audio_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(b''.join(audio_frames))
        except Exception as e:
            logger.error(f"保存录音失败: {e}")
            self._buffer.clear()
            return

        segment = VoiceSegment(
            audio_data=b''.join(audio_frames),
            timestamp=self._buffer[0][1],
            duration=duration,
            audio_path=audio_path
        )
        self._buffer.clear()

        self.on_speech(segment)


class AudioPlayer:
    def __init__(self):
        self._pygame_ready = False
        self._playing = False
        self._interrupt = threading.Event()
        self._play_thread = None

    def init(self):
        try:
            import pygame
            pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            self._pygame_ready = True
            logger.info("✓ 音频播放器初始化完成 (pygame)")
        except ImportError:
            logger.info("pygame 未安装，使用 sounddevice 作为播放器")
            self._pygame_ready = False
        except Exception as e:
            logger.warning(f"音频播放器初始化失败: {e}")
            self._pygame_ready = False

    def play_async(self, audio_path: str, on_done: Optional[Callable] = None):
        self.stop()
        self._interrupt.clear()
        self._playing = True

        if self._pygame_ready:
            self._play_pygame(audio_path, on_done)
        else:
            self._play_sounddevice(audio_path, on_done)

    def _play_pygame(self, audio_path: str, on_done: Optional[Callable] = None):
        def _play():
            try:
                import pygame
                pygame.mixer.music.load(audio_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy() and not self._interrupt.is_set():
                    time.sleep(0.05)
                pygame.mixer.music.stop()
            except Exception as e:
                logger.error(f"音频播放失败: {e}")
            finally:
                self._playing = False
                if on_done:
                    on_done()

        self._play_thread = threading.Thread(target=_play, daemon=True)
        self._play_thread.start()

    def _play_sounddevice(self, audio_path: str, on_done: Optional[Callable] = None):
        def _play():
            try:
                import sounddevice as sd
                import soundfile as sf

                data, samplerate = sf.read(audio_path)
                logger.debug(f"播放音频，时长: {len(data) / samplerate:.2f}秒")
                sd.play(data, samplerate)
                sd.wait()
            except Exception as e:
                logger.error(f"音频播放失败: {e}")
            finally:
                self._playing = False
                if on_done:
                    on_done()

        self._play_thread = threading.Thread(target=_play, daemon=True)
        self._play_thread.start()

    def stop(self):
        self._interrupt.set()
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=1.0)

        if self._pygame_ready:
            try:
                import pygame
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
            except Exception:
                pass
        else:
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass

        self._playing = False

    @property
    def is_playing(self):
        return self._playing


class VoiceLive:
    def __init__(self, config: Optional[VoiceConfig] = None):
        self.config = config or VoiceConfig.from_config()
        self.asr = None
        self.tts = None
        self.player = AudioPlayer()
        self.recorder = None
        self._running = False
        self._message_callback = None
        self._event_loop = None
        self._speaking = False
        self._interrupted = False
        self._processing = False
        self._speech_queue = Queue()
        self._tts_queue = Queue()
        self._agent = None

    def set_message_callback(self, callback: Callable[[str, str], None]):
        self._message_callback = callback

    def init(self, enable_asr: bool = True):
        if enable_asr:
            try:
                from .asr_engine import ASREngine
                self.asr = ASREngine(
                    model_name=self.config.asr.model,
                    language=self.config.asr.language
                )
                if not self.asr.is_ready:
                    logger.warning("ASR 初始化失败，语音识别功能不可用")
            except Exception as e:
                logger.error(f"ASR 初始化失败: {e}")
                self.asr = None

        self._init_tts()
        self.player.init()

        logger.info("正在预热 Agent 系统...")
        self._preload_agent()
        logger.info("✅ 所有语音对话组件加载完成！")

    def init_text_mode(self):
        self._init_tts()
        logger.info("正在预热 Agent 系统...")
        self._preload_agent()
        logger.info("✅ 文本模式组件加载完成！")

    def _init_tts(self):
        tts_provider = self.config.tts.provider

        try:
            if tts_provider == "bert-vits2":
                from .bert_vits2_tts import BertVITS2TTS
                self.tts = BertVITS2TTS()
                if not self.tts.is_ready:
                    logger.warning("BertVITS2 TTS 初始化失败，尝试回退到 TTSManager")
                    self.tts = self._fallback_tts()
            else:
                self.tts = self._fallback_tts()
        except ImportError:
            logger.warning(f"TTS 引擎 {tts_provider} 不可用，回退到 TTSManager")
            self.tts = self._fallback_tts()

    def _fallback_tts(self):
        try:
            from tts.tts_manager import TTSManager
            manager = TTSManager()
            if manager.is_initialized():
                return manager
            return None
        except Exception as e:
            logger.error(f"TTSManager 回退失败: {e}")
            return None

    def _preload_agent(self):
        try:
            from hakus.agent import AgentCore
            from hakus.permission import PermissionMode
            agent = AgentCore(
                model_type="deepseek",
                permission_mode=PermissionMode("auto"),
                working_dir=os.getcwd(),
            )
            # Store for later use
            self._agent = agent
            logger.info(f"  ✓ Agent 已就绪")
        except Exception as e:
            logger.warning(f"  ⚠ Agent 预热失败: {e}")

    def start_voice(self):
        self._running = True
        self._agent_loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(self._agent_loop)
            self._agent_loop.run_forever()

        self._agent_thread = threading.Thread(target=_run_loop, daemon=True)
        self._agent_thread.start()

        if self.asr and self.asr.is_ready:
            self.recorder = AudioRecorder(self.config, self._on_speech)
            self.recorder.start()
        else:
            logger.error("ASR 未就绪，无法启动语音识别")
            return

        tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        tts_thread.start()

        logger.info("🎤 语音对话模式已启动！可以说话了！按 Ctrl+C 停止")

    def stop_voice(self):
        self._running = False
        self._interrupted = True
        self.player.stop()
        if self.recorder:
            self.recorder.stop()
        if hasattr(self, '_agent_loop') and self._agent_loop.is_running():
            self._agent_loop.call_soon_threadsafe(self._agent_loop.stop)
        logger.info("语音对话模式已停止")

    def _on_speech(self, segment: VoiceSegment):
        if self._processing:
            logger.info("🔇 检测到打断！")
            self._interrupted = True
            self.player.stop()

        if not self.asr or not self.asr.is_ready:
            logger.error("ASR 未就绪")
            return

        text = self.asr.transcribe(segment.audio_path)
        if not text.strip():
            return

        logger.info(f"🗣️ 用户: {text}")

        self._speaking = True
        self._interrupted = False
        self._processing = True

        threading.Thread(
            target=self._stream_process,
            args=(text,),
            daemon=True
        ).start()

    def _stream_process(self, text: str):
        try:
            if self._agent is None:
                from hakus.agent import AgentCore
                from hakus.permission import PermissionMode
                self._agent = AgentCore(
                    model_type="deepseek",
                    permission_mode=PermissionMode("auto"),
                    working_dir=os.getcwd(),
                )
            agent = self._agent

            full_response = ""
            sentence_buffer = ""

            async def _run_stream():
                nonlocal full_response, sentence_buffer

                async for event in agent.run_turn(text):
                    if self._interrupted:
                        break

                    if TextDelta is not None and isinstance(event, TextDelta):
                        sentence_buffer += event.text
                        complete = self._try_complete_sentence(sentence_buffer)
                        if complete:
                            sentence_buffer = sentence_buffer[len(complete):]
                            full_response += complete
                            logger.info(f"💬 {self.config.live.character_name}: {complete}")
                            self._tts_queue.put(complete)
                    elif TurnFailed is not None and isinstance(event, TurnFailed):
                        logger.warning(
                            f"Live stream failed: [{event.code}] {event.error}"
                        )
                        break
                    elif CancelledEvent is not None and isinstance(event, CancelledEvent):
                        break

                if sentence_buffer.strip() and not self._interrupted:
                    full_response += sentence_buffer
                    logger.info(f"💬 {self.config.live.character_name}: {sentence_buffer}")
                    self._tts_queue.put(sentence_buffer)

            stream_future = asyncio.run_coroutine_threadsafe(
                _run_stream(),
                self._agent_loop
            )
            stream_future.result(timeout=60)

            self._tts_queue.put(None)

            if self._message_callback and full_response:
                self._message_callback(text, full_response)

        except Exception as e:
            logger.error(f"处理失败: {e}")
            self._tts_queue.put(None)
        finally:
            self._speaking = False
            self._processing = False

    def _try_complete_sentence(self, buffer: str) -> str:
        for sep in ['。', '！', '？', '\n']:
            idx = buffer.find(sep)
            if idx >= 0:
                return buffer[:idx + 1]
        if '，' in buffer and len(buffer) > 15:
            idx = buffer.rfind('，')
            if idx > 0:
                return buffer[:idx + 1]
        if len(buffer) > 40:
            return buffer
        return ""

    def _tts_worker(self):
        while self._running:
            try:
                text = self._tts_queue.get(timeout=0.5)
            except Empty:
                continue

            if text is None:
                self._speaking = False
                continue

            if self._interrupted:
                continue

            audio_path = None
            if self.tts:
                try:
                    if hasattr(self.tts, 'generate'):
                        audio_path = self.tts.generate(text)
                    elif hasattr(self.tts, 'generate_audio'):
                        if asyncio.iscoroutinefunction(self.tts.generate_audio):
                            loop = asyncio.new_event_loop()
                            audio_path = loop.run_until_complete(self.tts.generate_audio(text))
                            loop.close()
                        else:
                            audio_path = self.tts.generate_audio(text)
                except Exception as e:
                    logger.error(f"TTS failed: {e}")

            if audio_path and not self._interrupted:
                done_event = threading.Event()
                self.player.play_async(audio_path, on_done=done_event.set)
                done_event.wait(timeout=15)

    def _run_async(self, coro):
        try:
            asyncio.get_running_loop()
            has_running = True
        except RuntimeError:
            has_running = False

        if has_running:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=60)
        else:
            return asyncio.run(coro)

    async def _process_with_agent(self, text: str) -> str:
        if self._agent is None:
            from hakus.agent import AgentCore
            from hakus.permission import PermissionMode
            self._agent = AgentCore(
                model_type="deepseek",
                permission_mode=PermissionMode("auto"),
                working_dir=os.getcwd(),
            )
        response = await self._agent.process(text)
        return response.content if response and response.content else ""

    def process_text(self, text: str) -> Tuple[str, Optional[str]]:
        response = self._run_async(self._process_with_agent(text))
        audio_path = None
        if response and self.tts:
            if hasattr(self.tts, 'generate'):
                audio_path = self.tts.generate(response)
            elif hasattr(self.tts, 'generate_audio'):
                audio_path = self.tts.generate_audio(text)
        return response, audio_path

    def run(self):
        self.init()
        self.start_voice()

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n正在停止...")
            self.stop_voice()
