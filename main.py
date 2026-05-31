# main.py

import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from models.schemas import SlackMessage, PayslipInput, StreamlitMessage
from services.supabase_client import supabase
from agents.extractor import extract_payslip
from agents.legal import classify_all
from agents.supervisor import handle_message, handle_streamlit_message

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/app")
def serve_frontend():
    return FileResponse("static/index.html")

@app.get("/")
def root():
    return {"status": "Discovery Agent is running"}

@app.post("/slack/mensagem")
def receive_message(message: SlackMessage):
    handle_message(
        text=message.texto,
        channel_id=message.channel_id,
        thread_ts=message.thread_ts
    )
    return {"resposta": ""}

@app.post("/streamlit/mensagem")
def receive_streamlit_message(message: StreamlitMessage):
    result = handle_streamlit_message(
        texto=message.texto,
        discovery_id=message.discovery_id,
        pdfs_b64=message.pdfs_b64,
        tipo_pdf=message.tipo_pdf
    )
    return result

@app.get("/discovery/{discovery_id}/stage")
def get_discovery_stage(discovery_id: str):
    result = supabase.table("discoveries")\
        .select("stage")\
        .eq("id", discovery_id)\
        .limit(1)\
        .execute()
    if result.data:
        return {"stage": result.data[0]["stage"]}
    return {"stage": None}

@app.post("/extract")
def extract(input: PayslipInput):
    result = extract_payslip(input.payslip)
    return result

@app.post("/classify")
def classify(input: PayslipInput):
    extracted = extract_payslip(input.payslip)
    classified = classify_all(extracted["rubricas"])
    return {"rubricas": classified}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)