from pydantic import BaseModel
from typing import Optional

class SlackMessage(BaseModel):
    texto: str
    channel_id: str
    thread_ts: Optional[str] = None

class PayslipInput(BaseModel):
    payslip: str