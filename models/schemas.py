# schemas.py

from pydantic import BaseModel
from typing import Optional, List

class SlackMessage(BaseModel):
    texto: str
    channel_id: str
    thread_ts: Optional[str] = None

class PayslipInput(BaseModel):
    payslip: str

class StreamlitMessage(BaseModel):
    texto: str
    discovery_id: Optional[str] = None
    pdfs_b64: Optional[List[str]] = None  # lista de PDFs em base64
    tipo_pdf: Optional[str] = None        # "cct" ou "holerite"