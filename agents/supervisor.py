import json
from services.supabase_client import supabase
from agents.extractor import extract_payslip
from agents.legal import classify_all
from agents.blueprint import generate_calculation_order
from services.pdf_generator import generate_blueprint_pdf
from services.slack_uploader import upload_pdf_to_slack

def get_active_discovery(channel_id: str) -> dict | None:
    result = supabase.table("discoveries")\
        .select("*")\
        .eq("channel_id", channel_id)\
        .not_.eq("status", "completed")\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()

    if result.data:
        return result.data[0]
    return None


def create_discovery(company: str, channel_id: str) -> dict:
    result = supabase.table("discoveries").insert({
        "company": company,
        "channel_id": channel_id,
        "status": "started"
    }).execute()
    return result.data[0]


def update_discovery(discovery_id: str, updates: dict):
    supabase.table("discoveries")\
        .update(updates)\
        .eq("id", discovery_id)\
        .execute()


def handle_message(text: str, channel_id: str) -> str:
    text_clean = text.strip().lower()

    # Comando: iniciar [empresa]
    if text_clean.startswith("iniciar"):
        parts = text.strip().split(" ", 1)
        company = parts[1] if len(parts) > 1 else "empresa não informada"

        discovery = create_discovery(company, channel_id)
        return f"🔍 [DISCOVERY] Discovery iniciado para *{company}*.\n\nCole o holerite em Markdown para começar a extração."

    # Comando: gerar
    if text_clean == "gerar":
        discovery = get_active_discovery(channel_id)
        if not discovery:
            return "❌ Nenhum discovery ativo neste canal. Use `iniciar [empresa]` para começar."

        rubricas = discovery.get("rubricas", [])
        if not rubricas:
            return "⚠️ [RISCO] Nenhuma rubrica classificada ainda. Cole um holerite primeiro."

        update_discovery(discovery["id"], {"status": "completed"})
        return format_blueprint(discovery, channel_id)

    # Verifica se há discovery ativo aguardando resposta
    discovery = get_active_discovery(channel_id)

    if discovery:
        current_question = discovery.get("current_question")

        # Há uma pergunta aguardando resposta humana
        if current_question and discovery["status"] == "awaiting_response":
            return handle_human_response(text, discovery, current_question)

        # Discovery ativo mas sem pergunta pendente — interpreta como holerite
        return handle_payslip(text, discovery)

    return "ℹ️ Nenhum discovery ativo. Use `iniciar [empresa]` para começar."


def handle_payslip(payslip_text: str, discovery: dict) -> str:
    update_discovery(discovery["id"], {"status": "processing"})

    # Extrai rubricas
    extracted = extract_payslip(payslip_text)
    rubricas = extracted.get("rubricas", [])

    # Classifica com RAG
    classified = classify_all(rubricas)

    # Separa rubricas com confiança baixa para perguntar ao humano
    pending = [r for r in classified if r.get("confianca") == "baixa"]
    resolved = [r for r in classified if r.get("confianca") != "baixa"]

    # Salva estado
    updates = {
        "rubricas": resolved,
        "pending_questions": pending
    }

    if pending:
        first_question = pending[0]
        updates["status"] = "awaiting_response"
        updates["current_question"] = first_question
        updates["pending_questions"] = pending[1:]

        update_discovery(discovery["id"], updates)

        return (
            f"🔍 [DISCOVERY] Extraí e classifiquei {len(classified)} rubricas para *{discovery['company']}*.\n"
            f"{len(resolved)} resolvidas automaticamente, {len(pending)} precisam de esclarecimento.\n\n"
            f"❓ [PERGUNTA] Sobre a rubrica *{first_question['nome']}*:\n"
            f"{first_question.get('observacao', 'Preciso de mais informações sobre esta rubrica.')}\n\n"
            f"Como ela é calculada e qual sua natureza (salarial ou indenizatória)?"
        )

    updates["status"] = "classified"
    update_discovery(discovery["id"], updates)

    return (
        f"🔍 [DISCOVERY] Extraí e classifiquei {len(classified)} rubricas para *{discovery['company']}* com alta confiança.\n\n"
        f"Digite `gerar` para produzir a planta final."
    )


def handle_human_response(response_text: str, discovery: dict, current_question: dict) -> str:
    # Adiciona a resposta à rubrica e marca como resolvida
    current_question["resposta_humana"] = response_text
    current_question["confianca"] = "media"

    resolved = discovery.get("rubricas", []) + [current_question]
    pending = discovery.get("pending_questions", [])

    if pending:
        next_question = pending[0]
        remaining = pending[1:]

        update_discovery(discovery["id"], {
            "rubricas": resolved,
            "current_question": next_question,
            "pending_questions": remaining,
            "status": "awaiting_response"
        })

        return (
            f"✅ Resposta registrada para *{current_question['nome']}*.\n\n"
            f"❓ [PERGUNTA] Sobre a rubrica *{next_question['nome']}*:\n"
            f"{next_question.get('observacao', 'Preciso de mais informações.')}\n\n"
            f"Como ela é calculada e qual sua natureza?"
        )

    # Sem mais perguntas
    update_discovery(discovery["id"], {
        "rubricas": resolved,
        "current_question": None,
        "pending_questions": [],
        "status": "classified"
    })

    return (
        f"✅ Todas as rubricas esclarecidas.\n\n"
        f"Digite `gerar` para produzir a planta final."
    )


def format_blueprint(discovery: dict, channel_id: str) -> str:
    rubricas = discovery.get("rubricas", [])
    company = discovery.get("company", "")

    # Gera o grafo de ordem de cálculo
    order_data = generate_calculation_order(rubricas)

    # Gera o PDF
    pdf_bytes = generate_blueprint_pdf(discovery, order_data)

    # Monta mensagem de sumário para o Slack
    total = len(rubricas)
    alta = len([r for r in rubricas if r.get("confianca") == "alta"])
    media = len([r for r in rubricas if r.get("confianca") == "media"])
    baixa = len([r for r in rubricas if r.get("confianca") == "baixa"])

    summary = (
        f"✅ [PLANTA] Discovery concluído — *{company}*\n"
        f"Total de rubricas: {total} | "
        f"✅ {alta} confirmadas | "
        f"⚠️ {media} revisar | "
        f"❌ {baixa} requer decisão\n\n"
        f"Planta completa em anexo."
    )

    # Faz upload do PDF no Slack
    filename = f"planta_{company.lower().replace(' ', '_')}.pdf"
    upload_pdf_to_slack(pdf_bytes, filename, channel_id, summary)

    return summary