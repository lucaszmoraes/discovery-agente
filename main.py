import os
import uvicorn
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def raiz():
    return {"status": "Discovery Agente no ar"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)