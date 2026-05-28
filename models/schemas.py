from pydantic import BaseModel

class SlackMessage(BaseModel):
    texto: str

class PayslipInput(BaseModel):
    payslip: str