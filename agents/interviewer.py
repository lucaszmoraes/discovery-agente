# interviewer.py

import os
import json
from openai import OpenAI
from agents.legal import classify_rubrica

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

MAX_ATTEMPTS = 2  # max clarification rounds per rubrica


def interpret_response(user_response: str, pending_rubricas: list) -> dict:
    """
    Interprets a free-form user response and maps it to pending rubricas.
    Returns:
    {
        "resolved": [...],   # rubricas fully reclassified
        "vague": [...],      # rubricas that got a vague answer
        "unknown": [...],    # rubricas where user said they don't know
        "unaddressed": [...] # rubricas not mentioned at all
    }
    """
    pending_summary = "\n".join([
        f"- {r['nome']}: {r.get('observacao', '')}"
        for r in pending_rubricas
    ])

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": """Você é um especialista em folha de pagamento interpretando respostas do departamento pessoal (DP) de uma empresa.

Sua tarefa é mapear a resposta do usuário para as rubricas pendentes e classificar cada uma.

Para cada rubrica pendente, determine:
- "clara": o usuário forneceu informação suficiente para reclassificar com confiança
- "vaga": o usuário respondeu algo, mas a informação é insuficiente ou ambígua
- "nao_sabe": o usuário indicou que não tem a informação (ex: "não sei", "não temos isso documentado", "não lembro")
- "nao_endereçada": o usuário não mencionou essa rubrica na resposta

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
            },
            {
                "role": "user",
                "content": f"""Rubricas pendentes de esclarecimento:
{pending_summary}

Resposta do usuário:
{user_response}

Mapeie cada rubrica pendente para o que o usuário disse."""
            }
        ],
        temperature=0
    )

    content = response.choices[0].message.content
    return json.loads(content)


def reclassify_with_context(rubrica: dict, user_info: str) -> dict:
    """
    Calls the Legal Agent again with the additional context from the user.
    """
    enriched_rubrica = dict(rubrica)
    enriched_rubrica["contexto_adicional"] = user_info
    return classify_rubrica(enriched_rubrica)


def process_response(user_response: str, pending_rubricas: list) -> dict:
    """
    Main entry point. Processes a user response against all pending rubricas.
    Returns:
    {
        "closed": [...],    # rubricas fully resolved (reclassified or marked conservative)
        "still_pending": [] # rubricas that need another round
    }
    """
    mapping = interpret_response(user_response, pending_rubricas)
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

        attempts = rubrica.get("clarification_attempts", 0)

        if status == "clara":
            # Reclassify with new context
            reclassified = reclassify_with_context(rubrica, item["informacao_extraida"])
            reclassified["clarification_attempts"] = attempts + 1
            reclassified["resposta_humana"] = item["informacao_extraida"]
            closed.append(reclassified)

        elif status == "nao_sabe" or attempts >= MAX_ATTEMPTS - 1:
            # Apply conservative treatment and close
            rubrica["confianca"] = "baixa"
            rubrica["natureza"] = "salarial"
            rubrica["observacao"] = (
                rubrica.get("observacao", "") +
                " | Pendência assumida por precaução — tratar como salarial até confirmação jurídica."
            )
            rubrica["clarification_attempts"] = attempts + 1
            closed.append(rubrica)

        elif status == "vaga":
            # Keep pending for one more round if under limit
            rubrica["clarification_attempts"] = attempts + 1
            rubrica["observacao_vaga"] = item.get("justificativa", "")
            still_pending.append(rubrica)

        else:  # nao_endereçada
            # Keep pending if under attempt limit, else close conservative
            if attempts >= MAX_ATTEMPTS - 1:
                rubrica["confianca"] = "baixa"
                rubrica["natureza"] = "salarial"
                rubrica["observacao"] = (
                    rubrica.get("observacao", "") +
                    " | Não esclarecida pelo DP — tratada como salarial por precaução."
                )
                closed.append(rubrica)
            else:
                rubrica["clarification_attempts"] = attempts + 1
                still_pending.append(rubrica)

    return {
        "closed": closed,
        "still_pending": still_pending
    }