import os
import uvicorn
from fastapi import FastAPI
from models.schemas import SlackMessage, PayslipInput
from services.supabase_client import supabase
from agents.extractor import extract_payslip
from agents.legal import classify_all
from agents.supervisor import handle_message

app = FastAPI()

@app.get("/")
def root():
    return {"status": "Discovery Agent is running"}

@app.post("/slack/mensagem")
def receive_message(message: SlackMessage):
    response = handle_message(
        text=message.texto,
        channel_id=message.channel_id
    )
    return {"resposta": response}

@app.post("/extract")
def extract(input: PayslipInput):
    result = extract_payslip(input.payslip)
    return result

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

@app.post("/classify")
def classify(input: PayslipInput):
    from agents.extractor import extract_payslip
    
    # Extrai as rubricas do holerite
    extracted = extract_payslip(input.payslip)
    
    # Classifica cada rubrica com RAG
    classified = classify_all(extracted["rubricas"])
    
    return {"rubricas": classified}

@app.get("/test-slack")
def test_slack():
    from services.slack_uploader import upload_pdf_to_slack
    pdf_bytes = b"teste"
    result = upload_pdf_to_slack(pdf_bytes, "teste.pdf", "C0B6P8356GM", "teste de upload")
    return {"result": result}