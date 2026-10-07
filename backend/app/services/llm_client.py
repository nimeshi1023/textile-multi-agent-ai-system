from google import genai
from google.genai import types

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import LLMLog

import time
import logging


logger = logging.getLogger(__name__)


RETRYABLE_TERMS = [
    "503",
    "429",
    "UNAVAILABLE",
    "QUOTA",
    "TOO MANY REQUESTS",
    "TIMEOUT",
    "DEADLINE",
]


class LLMClient:

    def __init__(self):
        self.client = genai.Client(
            api_key=settings.GEMINI_API_KEY
        )

        self.model = settings.GEMINI_MODEL

        logger.info(
            f"Gemini LLM initialized with model: {self.model}"
        )

    def _log_to_db(
        self,
        prompt: str,
        response: str | None,
        latency: float,
        status: str,
        error: str | None = None
    ):
        db = SessionLocal()

        try:
            log_entry = LLMLog(
                prompt=prompt,
                response=response,
                latency_ms=latency,
                status=status,
                error_message=error
            )

            db.add(log_entry)
            db.commit()

        except Exception as e:
            logger.error(
                f"Failed to log to DB: {e}"
            )

        finally:
            db.close()

    def generate(
        self,
        prompt: str,
        max_retries: int = 5
    ) -> str:

        start_time = time.time()
        wait_time = 3.0

        for attempt in range(1, max_retries + 1):

            try:

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0
                    )
                )

                latency = (
                    time.time() - start_time
                ) * 1000

                response_text = response.text

                self._log_to_db(
                    prompt,
                    response_text,
                    latency,
                    "success"
                )

                return response_text

            except Exception as e:

                error_msg = str(e)

                logger.error(
                    f"Gemini error (attempt {attempt}/{max_retries}): "
                    f"{error_msg}"
                )

                upper_error = error_msg.upper()

                is_retryable = any(
                    term in upper_error
                    for term in RETRYABLE_TERMS
                )

                # Don't retry invalid model / API errors
                if not is_retryable:

                    latency = (
                        time.time() - start_time
                    ) * 1000

                    self._log_to_db(
                        prompt,
                        None,
                        latency,
                        "error",
                        error_msg
                    )

                    raise

                if attempt < max_retries:

                    logger.warning(
                        f"Gemini temporarily unavailable. "
                        f"Retrying in {wait_time}s..."
                    )

                    time.sleep(wait_time)

                    wait_time = min(
                        wait_time * 2,
                        15.0
                    )

                else:

                    latency = (
                        time.time() - start_time
                    ) * 1000

                    self._log_to_db(
                        prompt,
                        None,
                        latency,
                        "error",
                        error_msg
                    )

                    raise

        raise RuntimeError(
            "Gemini request failed after all retries."
        )

    def generate_multimodal(
        self,
        prompt: str,
        file_bytes: bytes,
        mime_type: str,
        max_retries: int = 5
    ) -> str:

        start_time = time.time()
        wait_time = 3.0

        for attempt in range(1, max_retries + 1):

            try:

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[
                        types.Part.from_bytes(
                            data=file_bytes,
                            mime_type=mime_type
                        ),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0
                    )
                )

                latency = (
                    time.time() - start_time
                ) * 1000

                response_text = response.text

                self._log_to_db(
                    prompt,
                    response_text,
                    latency,
                    "success"
                )

                return response_text

            except Exception as e:

                error_msg = str(e)

                logger.error(
                    f"Gemini multimodal error "
                    f"(attempt {attempt}/{max_retries}): "
                    f"{error_msg}"
                )

                upper_error = error_msg.upper()

                is_retryable = any(
                    term in upper_error
                    for term in RETRYABLE_TERMS
                )

                if not is_retryable:

                    latency = (
                        time.time() - start_time
                    ) * 1000

                    self._log_to_db(
                        prompt,
                        None,
                        latency,
                        "error",
                        error_msg
                    )

                    raise

                if attempt < max_retries:

                    logger.warning(
                        f"Gemini temporarily unavailable. "
                        f"Retrying in {wait_time}s..."
                    )

                    time.sleep(wait_time)

                    wait_time = min(
                        wait_time * 2,
                        15.0
                    )

                else:

                    latency = (
                        time.time() - start_time
                    ) * 1000

                    self._log_to_db(
                        prompt,
                        None,
                        latency,
                        "error",
                        error_msg
                    )

                    raise

        raise RuntimeError(
            "Gemini multimodal request failed after all retries."
        )