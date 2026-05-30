# interviewer.py

import os
import json
from openai import OpenAI
from agents.legal import classify_rubrica

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def interpret_response(user_response: str, pending_rubricas: list, history: list) -> dict:
    pending_summary = "\n".join([
        f"- {r['nome']}: {r.get('observacao', '')}"
        for r in pending_rubricas
    ])

    messages = [
        {
            "role": "system",
            "content": """Você é um especialista em folha de pagamento interpretando respostas do departamento pessoal (DP) de uma empresa.

Sua tarefa é mapear a resposta do usuário para as rubricas pendentes e classificar cada uma.

Para cada rubrica pendente, determine:
- "clara": o usuário forneceu informação suficiente para reclassificar com confiança. A resposta menciona explicitamente a rubrica ou seu contexto e esclarece a dúvida.
- "vaga": a resposta é insuficiente, ambígua, confusa, ou indica que o usuário não entendeu a pergunta (ex: "como assim?", "não entendi", "pode explicar melhor?", "o que você quer dizer?"). Nesse caso o sistema deve reformular a pergunta.
- "nao_sabe": o usuário indicou explicitamente que não tem a informação (ex: "não sei", "não temos isso documentado", "não lembro", "não temos essa informação").
- "nao_endereçada": o usuário não mencionou essa rubrica na resposta — nem direta nem indiretamente.

ATENÇÃO: "não entendi" e variações similares são SEMPRE "vaga", nunca "clara" ou "nao_sabe". O usuário não está dizendo que não tem a informação — está dizendo que não entendeu a pergunta.

Retorne APENAS um JSON válido, sem texto adicional:
{
  "mapeamento": [
    {
      "nome": "nome da rubrica",
      "status": "clara" | "vaga" | "nao_sabe" | "nao_endereçada",
      "informacao_extraida": "o que o usuário disse sobre essa rubrica, ou null se não endereçada",
      "justificativa": "por que você classificou assim"
    }
  ]
}"""
        }
    ]

    # Adiciona histórico real da conversa
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Adiciona contexto das rubricas pendentes + resposta atual
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

    content = response.choices[0].message.content
    return json.loads(content)


def reformulate_question(rubrica: dict, history: list) -> str:
    """
    Uses conversation history to reformulate a question about a rubrica
    in a clearer, simpler way than the original.
    """
    messages = [
        {
            "role": "system",
            "content": """Você é um especialista em folha de pagamento conversando com o departamento pessoal (DP) de uma empresa.

Sua tarefa é reformular uma pergunta sobre uma rubrica da folha de forma mais clara e simples.
O usuário não entendeu a pergunta anterior — reformule com linguagem mais direta, evite jargão jurídico, use exemplos concretos se ajudar.
A resposta deve ser APENAS a pergunta reformulada, sem introdução ou explicação adicional."""
        }
    ]

    # Adiciona histórico para o modelo ver o que já foi perguntado
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
    enriched_rubrica = dict(rubrica)
    enriched_rubrica["contexto_adicional"] = user_info
    return classify_rubrica(enriched_rubrica)


def process_response(user_response: str, pending_rubricas: list, history: list = None) -> dict:
    if history is None:
        history = []

    mapping = interpret_response(user_response, pending_rubricas, history)
    items = mapping.get("mapeamento", [])

    rubrica_by_name = {r["nome"]: r for r in pending_rubricas}

    closed = []
    still_pending = []

    for item in items:
        nome = item["nome"]
        status = item["status"]
        rubrica = rubrica_by_name.get(nome)

        if not rubrica:
            continue

        if status == "clara":
            reclassified = reclassify_with_context(rubrica, item["informacao_extraida"])
            reclassified["resposta_humana"] = item["informacao_extraida"]
            closed.append(reclassified)

        elif status == "nao_sabe":
            rubrica["confianca"] = "baixa"
            rubrica["natureza"] = "salarial"
            rubrica["observacao"] = (
                rubrica.get("observacao", "") +
                " | Pendência assumida por precaução — tratar como salarial até confirmação jurídica."
            )
            closed.append(rubrica)

        elif status == "vaga":
            # Reformula a pergunta usando o histórico
            rubrica["observacao"] = reformulate_question(rubrica, history)
            still_pending.append(rubrica)

        else:  # nao_endereçada
            still_pending.append(rubrica)

    return {
        "closed": closed,
        "still_pending": still_pending
    }