"""Service for transcribing Telegram voice messages via Groq API."""
from __future__ import annotations

import os
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit

import httpx
from aiogram import Bot
from dotenv import load_dotenv
from groq import AsyncGroq

from src.bot.utils.logging import logger
from src.config import config, env_path

class VoiceTranscriptionError(Exception):
    """Raised when voice transcription cannot be completed."""

class VoiceTranscriptionService:
    """Service for downloading Telegram voice files and transcribing them."""

    @staticmethod
    def _normalize_groq_base_url(base_url: str | None) -> str | None:
        """Normalize Groq base URL to avoid duplicated /openai prefix."""
        if not base_url:
            return None

        normalized = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)

        if "api.groq.com" not in parsed.netloc.lower():
            return normalized

        path = parsed.path.rstrip("/")

        if path.endswith("/openai/v1"):
            path = path[: -len("/openai/v1")]
        elif path.endswith("/openai"):
            path = path[: -len("/openai")]

        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

    @staticmethod
    def _normalize_groq_model(model: str | None, base_url: str | None) -> str:
        """Normalize transcription model for Groq compatibility."""
        normalized_model = (model or "").strip() or "whisper-large-v3"
        normalized_base_url = (base_url or "").lower()

        if "groq" in normalized_base_url and normalized_model == "whisper-1":
            return "whisper-large-v3"

        return normalized_model

    def __init__(
        self,
        bot: Bot,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        load_dotenv(env_path, override=True)

        self.bot = bot
        self.api_key = (
            api_key
            or os.getenv("GROQ_API_KEY")
            or os.getenv("LLM_API_KEY")
            or config.groq.api_key
        )
        raw_model = (
            model
            or os.getenv("GROQ_TRANSCRIPTION_MODEL")
            or os.getenv("LLM_TRANSCRIPTION_MODEL")
            or config.groq.transcription_model
        )
        self.base_url = self._normalize_groq_base_url(
            base_url
            or os.getenv("GROQ_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or config.groq.base_url
        )
        self.model = self._normalize_groq_model(raw_model, self.base_url)
        self.proxy_url = (
            os.getenv("HTTPS_PROXY")
            or os.getenv("HTTP_PROXY")
            or (
                config.bot.proxy.get("https") or config.bot.proxy.get("http")
                if config.bot.proxy
                else None
            )
        )

    async def transcribe_voice(self, file_id: str) -> str:
        """
        Download a Telegram voice file and transcribe it with Groq API.

        Args:
            file_id: Telegram file_id of the voice message

        Returns:
            Recognized text

        Raises:
            VoiceTranscriptionError: If download or transcription fails
        """
        if not self.api_key:
            raise VoiceTranscriptionError(
                "Не настроен ключ API для распознавания голосовых сообщений."
            )

        try:
            telegram_file = await self.bot.get_file(file_id)
            if not telegram_file.file_path:
                raise VoiceTranscriptionError("Telegram не вернул путь к голосовому файлу.")

            buffer = BytesIO()
            await self.bot.download_file(telegram_file.file_path, destination=buffer)
            audio_bytes = buffer.getvalue()
            filename = "voice_message.ogg"
        except VoiceTranscriptionError:
            raise
        except Exception as e:
            logger.error(f"Failed to download Telegram voice file {file_id}: {e}")
            raise VoiceTranscriptionError(
                "Не удалось скачать голосовое сообщение из Telegram."
            ) from e

        http_client: httpx.AsyncClient | None = None
        client: AsyncGroq | None = None

        try:
            if self.proxy_url:
                http_client = httpx.AsyncClient(proxy=self.proxy_url)

            client = AsyncGroq(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=http_client,
            )

            response = await client.audio.transcriptions.create(
                file=(filename, audio_bytes),
                model=self.model,
                temperature=0,
                response_format="verbose_json",
            )
            text = (response.text or "").strip()
        except ImportError as e:
            logger.error(f"SOCKS proxy support is not installed for transcription client: {e}")
            raise VoiceTranscriptionError(
                "Для распознавания через SOCKS-прокси не установлена зависимость socksio/httpx[socks]."
            ) from e
        except Exception as e:
            logger.error(f"Failed to transcribe voice file {file_id}: {e}")
            raise VoiceTranscriptionError(
                "Не удалось распознать голосовое сообщение через Groq API."
            ) from e
        finally:
            if client is not None:
                await client.close()
            elif http_client is not None:
                await http_client.aclose()

        if not text:
            raise VoiceTranscriptionError(
                "Распознавание завершилось без текста. Попробуйте отправить голосовое как есть или введите комментарий вручную."
            )

        return text