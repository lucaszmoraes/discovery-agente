import os
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from supabase import create_client

app = FastAPI()

# Lê as variáveis de ambiente que configuramos no Railway
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Cria o cliente Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

class SlackMessage(BaseModel):
    texto: str

@app.get("/")
def root():
    return {"status": "Discovery Agent is running"}

@app.post("/slack/mensagem")
def receive_message(message: SlackMessage):
    # Cria um novo discovery no Supabase
    result = supabase.table("discoveries").insert({
        "company": message.texto,
        "status": "started"
    }).execute()

    return {"resposta": f"Discovery iniciado para: {message.texto}"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)