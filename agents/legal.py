import os
import json
from openai import OpenAI
from services.rag import search_legal_docs

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def classify_rubrica(rubrica: dict) -> dict:
    query = f"{rubrica['nome']} natureza salarial incidências INSS FGTS IRRF"
    legal_context = search_legal_docs(query, limit=3)

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
Sua tarefa é classificar rubricas de folha de pagamento com rigor jurídico.

REGRAS DE CONFIANÇA — siga estritamente:
- "alta": a classificação tem base legal clara e inequívoca na legislação fornecida. Rubricas simples: salário base, INSS, IRRF, FGTS, VT, VR com regras fixas.
- "media": a rubrica tem base legal provável, mas depende de como a empresa a aplica na prática. Exemplos: sobreaviso (depende da escala), auxílio home office (salarial ou indenizatório depende da habitualidade), adiantamento salarial.
- "baixa": não é possível classificar com segurança sem informação adicional. Use "baixa" quando:
  * A rubrica pode ser salarial OU indenizatória dependendo de política interna (ex: bônus, PLR)
  * O critério de cálculo não está claro no holerite
  * Há risco de passivo trabalhista se a classificação estiver errada
  * A rubrica tem nome genérico que pode esconder naturezas diferentes

RUBRICAS QUE SEMPRE GERAM CONFIANÇA "baixa" SEM DOCUMENTAÇÃO ADICIONAL:
- Bônus (qualquer tipo): pode ser habitual (salarial) ou discricionário (indenizatório)
- PLR / Participação nos Resultados: precisa do acordo PLR para confirmar enquadramento na Lei 10.101/2000
- Comissão: precisa da política comercial para reconstruir a fórmula
- Sobreaviso: precisa da escala e do critério de cálculo

PRINCÍPIO CONSERVADOR: na dúvida, classifique como salarial e marque confiança "baixa".
Errar para o lado salarial protege a empresa de passivo. Errar para indenizatório gera multa.

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
  "observacao": "explique por que a confiança não é alta, qual informação falta e qual o risco se classificado errado"
}"""
            },
            {
                "role": "user",
                "content": f"""Classifique esta rubrica com base na legislação abaixo.
Seja conservador: prefira confiança baixa a classificar errado.

Rubrica:
{json.dumps(rubrica, ensure_ascii=False, indent=2)}

Legislação relevante:
{context_text}

Lembre: bônus, PLR, comissão e sobreaviso sem documentação adicional = confiança "baixa"."""
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