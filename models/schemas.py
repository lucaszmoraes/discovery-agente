from pydantic import BaseModel

class SlackMessage(BaseModel):
    texto: str
    channel_id: str

class PayslipInput(BaseModel):
    payslip: str