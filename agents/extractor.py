from openai import OpenAI

client = OpenAI()

def extract_payslip(payslip_markdown: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": """Você é um especialista em folha de pagamento brasileira (regime CLT).
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
            },
            {
                "role": "user",
                "content": f"Analise este holerite e extraia todas as rubricas:\n\n{payslip_markdown}"
            }
        ],
        temperature=0
    )

    import json
    content = response.choices[0].message.content
    return json.loads(content)