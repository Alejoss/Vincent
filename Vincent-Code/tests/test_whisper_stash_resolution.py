"""Offline regressions for the merged current/stashed transcription behavior."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import whisper_client as whisper
from src import llm_client


class WhisperResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.audio = Path(self.temp.name) / "audio.mp3"
        self.audio.write_bytes(b"test")
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_short_audio_retains_defaults_without_ffprobe(self):
        with patch.object(whisper, "transcribe_openai", return_value="hola") as send, \
             patch("src.audio_extract.get_media_duration_seconds") as duration:
            self.assertEqual(whisper.transcribe_audio(self.audio, provider="openai"), "hola")
        duration.assert_not_called()
        send.assert_called_once_with(str(self.audio), language="es", timeout=120.0)

    def test_language_timeout_and_env_duration_chunking(self):
        os.environ.update(WHISPER_OPENAI_TIMEOUT="600", WHISPER_CHUNK_LONG_AUDIO="1")
        chunk = Path(self.temp.name) / "chunk.mp3"
        chunk.write_bytes(b"chunk")
        with patch("src.audio_extract.get_media_duration_seconds", return_value=1200), \
             patch("src.audio_extract.split_audio", return_value=[chunk]) as split, \
             patch.object(whisper, "transcribe_openai", return_value="hello") as send:
            self.assertEqual(whisper.transcribe_audio(self.audio, provider="openai", language="en"), "hello")
        split.assert_called_once()
        send.assert_called_once_with(str(chunk), language="en", timeout=600.0)
        self.assertFalse(Path(split.call_args.args[1]).exists(), "temporary chunks should be cleaned up")

    def test_explicit_false_overrides_chunking_environment(self):
        os.environ["WHISPER_CHUNK_LONG_AUDIO"] = "1"
        with patch.object(whisper, "transcribe_openai", return_value="ok") as send, \
             patch("src.audio_extract.get_media_duration_seconds") as duration:
            whisper.transcribe_audio(self.audio, provider="openai", chunk_long_audio=False, timeout=45)
        duration.assert_not_called()
        self.assertEqual(send.call_args.kwargs["timeout"], 45)

    def test_large_files_are_chunked_even_with_duration_disabled(self):
        with patch.object(whisper, "MAX_FILE_BYTES", 3), \
             patch("src.audio_extract.split_audio", return_value=[]) as split:
            with self.assertRaisesRegex(RuntimeError, "Empty transcript"):
                whisper.transcribe_audio(self.audio, provider="openai", chunk_long_audio=False)
        split.assert_called_once()

    def test_empty_chunk_result_and_oversized_chunk_fail(self):
        with patch("src.audio_extract.get_media_duration_seconds", return_value=1200), \
             patch("src.audio_extract.split_audio", return_value=[self.audio]), \
             patch.object(whisper, "transcribe_openai", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "Empty transcript"):
                whisper.transcribe_audio(self.audio, provider="openai", chunk_long_audio=True)
        with patch.object(whisper, "MAX_FILE_BYTES", 3), \
             patch("src.audio_extract.split_audio", return_value=[self.audio]), \
             patch.object(whisper, "transcribe_openai") as send:
            with self.assertRaisesRegex(ValueError, "Chunk still too large"):
                whisper.transcribe_audio(self.audio, provider="openai")
        send.assert_not_called()

    def test_invalid_timeout_falls_back_to_current_default(self):
        for value in ("invalid", "-1", "nan", "inf"):
            os.environ["WHISPER_OPENAI_TIMEOUT"] = value
            self.assertEqual(whisper._openai_timeout(None, 120), 120)

    def test_cli_honors_model_and_language(self):
        cache = Path(self.temp.name)
        (cache / "cli_out").mkdir()
        (cache / "cli_out" / "audio.txt").write_text("bonjour", encoding="utf-8")
        with patch.object(whisper.shutil, "which", return_value="whisper"), \
             patch.object(whisper.subprocess, "run") as run:
            result = whisper.transcribe_whisper_local(self.audio, language="fr", model_name="medium", cache_dir=cache)
        self.assertEqual(result, "bonjour")
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--model") + 1], "medium")
        self.assertEqual(args[args.index("--language") + 1], "fr")

    def test_gpu_failure_retains_cpu_fallback(self):
        model = Mock()
        model.transcribe.return_value = ([SimpleNamespace(text=" hello ")], None)
        factory = Mock(side_effect=[RuntimeError("CUDA unavailable"), model])
        module = SimpleNamespace(WhisperModel=factory)
        with patch.dict("sys.modules", {"faster_whisper": module}), \
             patch.object(whisper.shutil, "which", return_value=None), \
             patch.object(whisper, "_ensure_nvidia_dll_path") as dll:
            result = whisper.transcribe_audio(self.audio, provider="local", language="en", cache_dir=self.temp.name)
        self.assertEqual(result, "hello")
        dll.assert_called_once()
        self.assertEqual(factory.call_args_list[0].kwargs, {"device": "cuda", "compute_type": "float16"})
        self.assertEqual(factory.call_args_list[1].kwargs, {"device": "cpu", "compute_type": "int8"})
        model.transcribe.assert_called_once_with(str(self.audio), language="en")

    def test_knowledge_helper_preserves_editorial_config(self):
        with patch.object(llm_client, "_load_env"), \
             patch.dict(os.environ, {"KNOWLEDGE_EXTRACTION_MODEL": "knowledge-model", "LLM_MODEL": "classifier"}):
            self.assertEqual(llm_client.build_knowledge_llm_config(provider="openai").model, "knowledge-model")
            self.assertEqual(llm_client.build_editorial_llm_config(provider="openai", model="editorial").model, "editorial")


if __name__ == "__main__":
    unittest.main()
