import os
import json
from openai import OpenAI
from services.rag import search_legal_docs

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def classify_rubrica(rubrica: dict) -> dict:
    # Busca legislação relevante para essa rubrica
    query = f"{rubrica['nome']} natureza salarial incidências INSS FGTS IRRF"
    legal_context = search_legal_docs(query, limit=3)

    # Monta o contexto legal para o prompt
    context_text = "\n\n".join([
        f"[{doc['source']}] {doc['title']}:\n{doc['content']}"
        for doc in legal_context
    ])

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": """Você é um especialista em legislação trabalhista brasileira (regime CLT).
Sua tarefa é classificar uma rubrica de folha de pagamento com base na legislação fornecida.

Para cada rubrica, retorne APENAS um JSON válido, sem texto adicional, no formato:
{
  "nome": "nome da rubrica",
  "tipo": "provento" ou "desconto",
  "natureza": "salarial" ou "indenizatoria",
  "formula": "descrição de como o valor é calculado",
  "incide_inss": true ou false,
  "incide_irrf": true ou false,
  "incide_fgts": true ou false,
  "reflexo_ferias": true ou false,
  "reflexo_13": true ou false,
  "confianca": "alta", "media" ou "baixa",
  "base_legal": "artigo ou súmula que fundamenta a classificação",
  "observacao": "riscos ou alertas relevantes"
}"""
            },
            {
                "role": "user",
                "content": f"""Classifique esta rubrica com base na legislação abaixo:

Rubrica:
{json.dumps(rubrica, ensure_ascii=False, indent=2)}

Legislação relevante:
{context_text}"""
            }
        ],
        temperature=0
    )

    content = response.choices[0].message.content
    return json.loads(content)


def classify_all(rubricas: list) -> list:
    results = []
    for rubrica in rubricas:
        classified = classify_rubrica(rubrica)
        results.append(classified)
    return results