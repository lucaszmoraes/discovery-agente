import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def generate_calculation_order(rubricas: list) -> dict:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": """Você é um especialista em folha de pagamento brasileira (regime CLT).
Dada uma lista de rubricas classificadas, sua tarefa é determinar a ordem correta de cálculo para que o salário líquido seja calculado corretamente.

Regras obrigatórias de ordem:
1. Proventos fixos (salário base) sempre primeiro
2. Proventos variáveis que dependem de outros (ex: DSR sobre comissão) depois das suas bases
3. Base do INSS = soma de todos os proventos com incide_inss = true
4. INSS calculado sobre a base do INSS
5. Base do IRRF = base INSS - INSS - deduções legais
6. IRRF calculado sobre a base do IRRF
7. Base do FGTS = mesma base do INSS
8. FGTS calculado sobre a base do FGTS
9. Demais descontos (VT, etc) após os descontos legais
10. Líquido = total proventos - total descontos

Retorne APENAS um JSON válido, sem texto adicional, no formato:
{
  "ordem": [
    {
      "passo": 1,
      "rubrica": "nome da rubrica",
      "depende_de": ["lista de rubricas que precisam ser calculadas antes"],
      "observacao": "por que este passo vem aqui"
    }
  ],
  "bases": {
    "base_inss": ["lista de rubricas que compõem a base do INSS"],
    "base_irrf": ["lista de rubricas que compõem a base do IRRF"],
    "base_fgts": ["lista de rubricas que compõem a base do FGTS"]
  },
  "formula_liquido": "descrição da fórmula final do líquido"
}"""
            },
            {
                "role": "user",
                "content": f"""Gere o grafo de ordem de cálculo para estas rubricas:

{json.dumps(rubricas, ensure_ascii=False, indent=2)}"""
            }
        ],
        temperature=0
    )

    content = response.choices[0].message.content
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content.strip())


def format_calculation_order(order_data: dict) -> str:
    lines = ["\n*ORDEM DE CÁLCULO*"]

    for step in order_data.get("ordem", []):
        deps = step.get("depende_de", [])
        dep_text = f" ← depende de: {', '.join(deps)}" if deps else ""
        lines.append(f"{step['passo']}. *{step['rubrica']}*{dep_text}")
        lines.append(f"   _{step.get('observacao', '')}_")

    bases = order_data.get("bases", {})
    if bases:
        lines.append("\n*BASES DE CÁLCULO*")
        lines.append(f"• Base INSS: {', '.join(bases.get('base_inss', []))}")
        lines.append(f"• Base IRRF: {', '.join(bases.get('base_irrf', []))}")
        lines.append(f"• Base FGTS: {', '.join(bases.get('base_fgts', []))}")

    formula = order_data.get("formula_liquido", "")
    if formula:
        lines.append(f"\n*FÓRMULA DO LÍQUIDO*\n{formula}")

    return "\n".join(lines)