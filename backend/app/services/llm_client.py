from groq import Groq

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import LLMLog

import time
import logging


logger = logging.getLogger(__name__)


# Callers parse the reply with json.loads, so ask for bare JSON.
# (Groq's JSON mode also requires the word "JSON" in the messages.)
JSON_SYSTEM_PROMPT = (
    "You are a data extraction and analysis component in a backend system. "
    "Respond with a single valid JSON object only, with no prose before or "
    "after it and no Markdown code fences."
)


class LLMClient:

    def __init__(self):
        # The SDK retries 408/409/429/5xx and connection errors
        # with exponential backoff.
        self.client = Groq(
            api_key=settings.GROQ_API_KEY,
            max_retries=5
        )

        self.model = settings.GROQ_MODEL

        logger.info(
            f"Groq LLM initialized with model: {self.model}"
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
        prompt: str
    ) -> str:

        start_time = time.time()

        try:

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": JSON_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )

            response_text = (
                response.choices[0].message.content or ""
            ).strip()

            latency = (time.time() - start_time) * 1000

            self._log_to_db(
                prompt,
                response_text,
                latency,
                "success"
            )

            return response_text

        except Exception as e:

            error_msg = str(e)

            logger.error(f"Groq error: {error_msg}")

            latency = (time.time() - start_time) * 1000

            self._log_to_db(
                prompt,
                None,
                latency,
                "error",
                error_msg
            )

            raise

    def generate_multimodal(
        self,
        prompt: str,
        file_bytes: bytes,
        mime_type: str
    ) -> str:

        # Only reached for PDFs with no extractable text (scanned images).
        # Groq's production models are text-only.
        raise RuntimeError(
            "This PDF has no readable text (it looks like a scanned image). "
            "Groq models can't read scanned documents - please upload a "
            "text-based PDF or paste the order details as a message."
        )
