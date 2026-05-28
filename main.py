import os
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# Modelo que define o formato do JSON que o n8n vai mandar
class MensagemSlack(BaseModel):
    texto: str

@app.get("/")
def raiz():
    return {"status": "Discovery Agente no ar"}

@app.post("/slack/mensagem")
def receber_mensagem(mensagem: MensagemSlack):
    return {"resposta": f"Recebi sua mensagem: {mensagem.texto}"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)