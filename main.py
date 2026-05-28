import os
import uvicorn
from fastapi import FastAPI
from models.schemas import SlackMessage
from services.supabase_client import supabase

app = FastAPI()

@app.get("/")
def root():
    return {"status": "Discovery Agent is running"}

@app.post("/slack/mensagem")
def receive_message(message: SlackMessage):
    result = supabase.table("discoveries").insert({
        "company": message.texto,
        "status": "started"
    }).execute()

    return {"resposta": f"Discovery iniciado para: {message.texto}"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)