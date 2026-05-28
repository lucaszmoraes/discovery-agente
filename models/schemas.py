from pydantic import BaseModel

class SlackMessage(BaseModel):
    texto: str