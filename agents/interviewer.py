# interviewer.py

import os
import json
from openai import OpenAI
from agents.legal import classify_rubrica

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

AGENT = {
    "name": "interviewer",
    "description": "Interpreta respostas livres do DP sobre rubricas ambíguas, mapeia cada resposta para a rubrica correta e reformula perguntas quando o usuário não entendeu. Deve ser acionado quando há rubricas pendentes de esclarecimento e o usuário enviou uma resposta.",
    "system_prompt": """Você é um especialista em folha de pagamento interpretando respostas do departamento pessoal (DP) de uma empresa.

Sua tarefa é mapear a resposta do usuário para as rubricas pendentes e classificar cada uma.

Para cada rubrica pendente, determine:
- "clara": o usuário forneceu informação suficiente para reclassificar com confiança.
- "vaga": a resposta é insuficiente, ambígua, confusa, ou indica que o usuário não entendeu a pergunta (ex: "como assim?", "não entendi", "pode explicar melhor?"). Nesse caso o sistema deve reformular a pergunta.
- "nao_sabe": o usuário indicou explicitamente que não tem a informação (ex: "não sei", "não temos isso documentado").
- "nao_endereçada": o usuário não mencionou essa rubrica na resposta.

ATENÇÃO: "não entendi" e variações similares são SEMPRE "vaga", nunca "clara" ou "nao_sabe".

Retorne APENAS um JSON válido, sem texto adicional:
{
  "mapeamento": [
    {
      "nome": "nome da rubrica",
      "status": "clara" | "vaga" | "nao_sabe" | "nao_endereçada",
      "informacao_extraida": "o que o usuário disse sobre essa rubrica, ou null",
      "justificativa": "por que você classificou assim"
    }
  ]
}"""
}

REFORMULATE_PROMPT = """Você é um especialista em folha de pagamento conversando com o departamento pessoal (DP) de uma empresa.

Sua tarefa é reformular uma pergunta sobre uma rubrica da folha de forma mais clara e simples.
O usuário não entendeu a pergunta anterior — reformule com linguagem mais direta, evite jargão jurídico, use exemplos concretos se ajudar.
A resposta deve ser APENAS a pergunta reformulada, sem introdução ou explicação adicional."""


def interpret_response(user_response: str, pending_rubricas: list, history: list) -> dict:
    pending_summary = "\n".join([
        f"- {r['nome']}: {r.get('observacao', '')}"
        for r in pending_rubricas
    ])

    messages = [{"role": "system", "content": AGENT["system_prompt"]}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({
        "role": "user",
        "content": f"""Rubricas ainda pendentes de esclarecimento:
{pending_summary}

Resposta do usuário:
{user_response}

Mapeie cada rubrica pendente para o que o usuário disse."""
    })

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        temperature=0
    )
    return json.loads(response.choices[0].message.content)


def reformulate_question(rubrica: dict, history: list) -> str:
    messages = [{"role": "system", "content": REFORMULATE_PROMPT}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({
        "role": "user",
        "content": f"""Reformule a pergunta sobre a rubrica "{rubrica['nome']}" de forma mais simples e direta.
Contexto original da dúvida: {rubrica.get('observacao', '')}
O usuário não entendeu a pergunta anterior. Tente de outro ângulo."""
    })

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        temperature=0.3
    )
    return response.choices[0].message.content.strip()


def reclassify_with_context(rubrica: dict, user_info: str) -> dict:
    enriched = dict(rubrica)
    enriched["contexto_adicional"] = user_info
    return classify_rubrica(enriched)


def process_response(user_response: str, pending_rubricas: list, history: list = None) -> dict:
    if history is None:
        history = []

    mapping = interpret_response(user_response, pending_rubricas, history)
    items = mapping.get("mapeamento", [])
    rubrica_by_name = {r["nome"]: r for r in pending_rubricas}

    closed = []
    still_pending = []

    for item in items:
        rubrica = rubrica_by_name.get(item["nome"])
        if not rubrica:
            continue

        if item["status"] == "clara":
            reclassified = reclassify_with_context(rubrica, item["informacao_extraida"])
            reclassified["resposta_humana"] = item["informacao_extraida"]
            closed.append(reclassified)

        elif item["status"] == "nao_sabe":
            rubrica["confianca"] = "baixa"
            rubrica["natureza"] = "salarial"
            rubrica["observacao"] += " | Pendência assumida por precaução — tratar como salarial até confirmação jurídica."
            closed.append(rubrica)

        elif item["status"] == "vaga":
            rubrica["observacao"] = reformulate_question(rubrica, history)
            still_pending.append(rubrica)

        else:
            still_pending.append(rubrica)

    return {"closed": closed, "still_pending": still_pending}