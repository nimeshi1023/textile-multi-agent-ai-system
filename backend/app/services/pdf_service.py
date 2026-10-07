import pdfplumber
import io

class PDFService:
    @staticmethod
    def extract_text(file_bytes: bytes) -> str | None:
        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                text = ""
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
                return text if text.strip() else None
        except Exception:
            return None
