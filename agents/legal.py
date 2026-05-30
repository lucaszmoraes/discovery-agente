# legal.py

import os
import json
from openai import OpenAI
from services.rag import search_legal_docs

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

AGENT = {
    "name": "legal",
    "description": "Classifica rubricas de folha com base na legislação trabalhista brasileira (CLT, INSS, IRRF, FGTS) e na CCT da empresa, usando RAG. Deve ser acionado após a extração das rubricas.",
    "system_prompt": """Você é um especialista em legislação trabalhista brasileira (regime CLT).
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
  "observacao": "duas partes obrigatórias, separadas por quebra de linha: (1) motivo da dúvida em uma frase direta com a base legal ou princípio que gera a incerteza; (2) uma pergunta direta e cirúrgica que, se respondida, sanará a dúvida"
}"""
}


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
            {"role": "system", "content": AGENT["system_prompt"]},
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
    return [classify_rubrica(r) for r in rubricas]