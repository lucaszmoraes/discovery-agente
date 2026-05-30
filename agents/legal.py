# legal.py

import json
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

AGENT = {
    "name": "extractor",
    "description": "Lê holerites em Markdown e extrai todas as rubricas (nome, tipo, valor). Deve ser acionado quando o usuário colar um holerite.",
    "system_prompt": """Você é um especialista em folha de pagamento brasileira (regime CLT).
Sua tarefa é analisar um holerite e extrair todas as rubricas (verbas) encontradas.

Para cada rubrica, retorne:
- nome: nome exato como aparece no holerite
- tipo: "provento" ou "desconto"
- valor: valor numérico encontrado
- observacao: qualquer detalhe relevante (ex: "percentual aplicado", "base de cálculo visível")

Retorne APENAS um JSON válido, sem texto adicional, no formato:
{
  "rubricas": [
    {
      "nome": "Salário Base",
      "tipo": "provento",
      "valor": 5000.00,
      "observacao": ""
    }
  ]
}"""
}


def extract_payslip(payslip_markdown: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": AGENT["system_prompt"]},
            {"role": "user", "content": f"Analise este holerite e extraia todas as rubricas:\n\n{payslip_markdown}"}
        ],
        temperature=0
    )
    content = response.choices[0].message.content
    return json.loads(content)