import os
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client

load_dotenv()

# Clients
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
supabase = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")
)

# Legal documents to insert
DOCUMENTS = [
    {
        "title": "CLT Art. 457 - Remuneração e Salário",
        "source": "CLT",
        "content": """CLT Art. 457 - Compreendem-se na remuneração do empregado, para todos os efeitos legais, além do salário devido e pago diretamente pelo empregador, como contraprestação do serviço, as gorjetas que receber.

§ 1o Integram o salário a importância fixa estipulada, as gratificações legais e as comissões pagas pelo empregador.

§ 2o As importâncias, ainda que habituais, pagas a título de ajuda de custo, auxílio-alimentação, vedado seu pagamento em dinheiro, diárias para viagem, prêmios e abonos não integram a remuneração do empregado, não se incorporam ao contrato de trabalho e não constituem base de incidência de qualquer encargo trabalhista e previdenciário.

§ 4o Consideram-se prêmios as liberalidades concedidas pelo empregador em forma de bens, serviços ou valor em dinheiro a empregado ou a grupo de empregados, em razão de desempenho superior ao ordinariamente esperado no exercício de suas atividades."""
    },
    {
        "title": "CLT Art. 458 - Salário In Natura",
        "source": "CLT",
        "content": """CLT Art. 458 - Além do pagamento em dinheiro, compreende-se no salário, para todos os efeitos legais, a alimentação, habitação, vestuário ou outras prestações in natura que a empresa, por força do contrato ou do costume, fornecer habitualmente ao empregado.

§ 2o Para os efeitos previstos neste artigo, não serão consideradas como salário as seguintes utilidades concedidas pelo empregador:
I – vestuários, equipamentos e outros acessórios fornecidos aos empregados e utilizados no local de trabalho;
II – educação, em estabelecimento de ensino próprio ou de terceiros;
III – transporte destinado ao deslocamento para o trabalho e retorno;
IV – assistência médica, hospitalar e odontológica;
V – seguros de vida e de acidentes pessoais;
VI – previdência privada."""
    },
    {
        "title": "CLT Art. 129-133 - Férias Anuais",
        "source": "CLT",
        "content": """CLT Art. 129 - Todo empregado terá direito anualmente ao gozo de um período de férias, sem prejuízo da remuneração.

Art. 130 - Após cada período de 12 meses de vigência do contrato de trabalho, o empregado terá direito a férias, na seguinte proporção:
I - 30 dias corridos, quando não houver faltado ao serviço mais de 5 vezes;
II - 24 dias corridos, quando houver tido de 6 a 14 faltas;
III - 18 dias corridos, quando houver tido de 15 a 23 faltas;
IV - 12 dias corridos, quando houver tido de 24 a 32 faltas.

Art. 133 - Não terá direito a férias o empregado que, no curso do período aquisitivo:
I - deixar o emprego e não for readmitido dentro de 60 dias;
II - permanecer em gozo de licença, com percepção de salários, por mais de 30 dias;
IV - tiver percebido da Previdência Social prestações de acidente de trabalho ou de auxílio-doença por mais de 6 meses."""
    },
    {
        "title": "Lei 605/49 - Repouso Semanal Remunerado (DSR)",
        "source": "Lei 605/1949",
        "content": """Art. 1º Todo empregado tem direito ao repouso semanal remunerado de vinte e quatro horas consecutivas, preferentemente aos domingos e, nos limites das exigências técnicas das empresas, nos feriados civis e religiosos.

Art. 6º Não será devida a remuneração quando, sem motivo justificado, o empregado não tiver trabalhado durante toda a semana anterior, cumprindo integralmente o seu horário de trabalho.

Art. 7º A remuneração do repouso semanal corresponderá:
a) para os que trabalham por dia, semana, quinzena ou mês, à de um dia de serviço, computadas as horas extraordinárias habitualmente prestadas;
c) para os que trabalham por tarefa ou peça, o equivalente ao salário correspondente às tarefas ou peças feitas durante a semana, no horário normal de trabalho, dividido pelos dias de serviço efetivamente prestados.

§ 2º Consideram-se já remunerados os dias de repouso semanal do empregado mensalista cujo cálculo de salário mensal seja efetuado na base do número de dias do mês ou de 30 diárias."""
    },
    {
        "title": "Súmula TST 27 - DSR sobre Comissões",
        "source": "Súmula TST 27",
        "content": """Súmula nº 27 do TST - COMISSIONISTA

É devida a remuneração do repouso semanal e dos dias feriados ao empregado comissionista, ainda que pracista.

Res. 121/2003, DJ 19, 20 e 21.11.2003

Interpretação: As comissões integram a remuneração do empregado e geram reflexo no DSR. O cálculo do DSR sobre comissões é feito dividindo o total de comissões do mês pelos dias úteis trabalhados, multiplicando pelo número de domingos e feriados do período. O DSR sobre comissão tem natureza salarial e gera reflexos em férias, 13º salário e FGTS."""
    },
    {
        "title": "Lei 10.101/2000 - Participação nos Lucros e Resultados (PLR)",
        "source": "Lei 10.101/2000",
        "content": """Art. 1o Esta Lei regula a participação dos trabalhadores nos lucros ou resultados da empresa como instrumento de integração entre o capital e o trabalho e como incentivo à produtividade, nos termos do art. 7o, inciso XI, da Constituição.

Art. 2o A participação nos lucros ou resultados será objeto de negociação entre a empresa e seus empregados, mediante um dos procedimentos a seguir descritos, escolhidos pelas partes de comum acordo.

Art. 3o A participação de que trata o art. 2o não substitui ou complementa a remuneração devida a qualquer empregado, nem constitui base de incidência de qualquer encargo trabalhista, não se lhe aplicando o princípio da habitualidade.

Interpretação: A PLR tem natureza indenizatória — não integra o salário, não incide INSS, FGTS nem gera reflexos em férias ou 13º. Exige acordo coletivo ou comissão paritária. Deve ser paga no máximo duas vezes por ano."""
    },
    {
        "title": "Tabela INSS 2026 - Alíquotas Progressivas",
        "source": "Portaria Interministerial MPS/MF nº 13/2026",
        "content": """Tabela de contribuição ao INSS para empregados CLT, empregados domésticos e trabalhadores avulsos — vigência a partir de janeiro de 2026.

Faixas e alíquotas (modelo progressivo — cada alíquota incide apenas sobre a parcela do salário dentro da faixa):
- 7,5% para salário até R$ 1.621,00
- 9,0% para salário entre R$ 1.621,01 e R$ 2.902,84
- 12,0% para salário entre R$ 2.902,85 e R$ 4.354,27
- 14,0% para salário entre R$ 4.354,28 e R$ 8.475,55 (teto)

Teto de contribuição: R$ 8.475,55. Salário mínimo previdenciário: R$ 1.621,00.
Desconto máximo mensal: aproximadamente R$ 988,09.
O cálculo é progressivo: cada faixa incide apenas sobre a parcela do salário que se encaixa naquele intervalo."""
    },
    {
        "title": "Tabela IRRF 2026 - Incidência Mensal e Redução",
        "source": "Lei 15.270/2025 e art. 3º da Lei 9.250/1995",
        "content": """Tabela de Incidência Mensal do IRRF — a partir de janeiro de 2026:
- Até R$ 2.428,80: isento
- De R$ 2.428,81 até R$ 2.826,65: alíquota 7,5% — dedução R$ 182,16
- De R$ 2.826,66 até R$ 3.751,05: alíquota 15,0% — dedução R$ 394,16
- De R$ 3.751,06 até R$ 4.664,68: alíquota 22,5% — dedução R$ 675,49
- Acima de R$ 4.664,68: alíquota 27,5% — dedução R$ 908,73

Tabela de Redução do Imposto Mensal — vigência a partir de janeiro de 2026 (Lei 15.270/2025):
- Até R$ 5.000,00 de rendimento tributável: redução de até R$ 312,89 — imposto zero (isento na prática)
- De R$ 5.000,01 até R$ 7.350,00: redução = R$ 978,62 – (0,133145 × rendimento mensal) — desconto parcial decrescente
- A partir de R$ 7.350,00: sem redução — tributação normal pela tabela progressiva

Importante: o cálculo correto em 2026 exige duas etapas — primeiro aplica a tabela progressiva, depois subtrai a redução mensal."""
    }
]

def generate_embedding(text: str) -> list:
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

def seed():
    print(f"Inserindo {len(DOCUMENTS)} documentos legais...")
    
    for doc in DOCUMENTS:
        print(f"  Processando: {doc['title']}")
        
        embedding = generate_embedding(doc["content"])
        
        supabase.table("legal_documents").insert({
            "title": doc["title"],
            "source": doc["source"],
            "content": doc["content"],
            "embedding": embedding
        }).execute()
        
        print(f"  ✓ Inserido")
    
    print("\nConcluído.")

if __name__ == "__main__":
    seed()