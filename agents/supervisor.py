import json
from services.supabase_client import supabase
from agents.extractor import extract_payslip
from agents.legal import classify_all
from agents.blueprint import generate_calculation_order
from services.pdf_generator import generate_blueprint_pdf
from services.slack_uploader import upload_pdf_to_slack, post_message_to_slack


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


def create_discovery(company: str, channel_id: str, thread_ts: str = None) -> dict:
    result = supabase.table("discoveries").insert({
        "company": company,
        "channel_id": channel_id,
        "status": "started",
        "thread_ts": thread_ts
    }).execute()
    return result.data[0]


def update_discovery(discovery_id: str, updates: dict):
    supabase.table("discoveries")\
        .update(updates)\
        .eq("id", discovery_id)\
        .execute()


def handle_message(text: str, channel_id: str, thread_ts: str = None) -> str:
    text_clean = text.strip().lower()

    # Comando: iniciar [empresa]
    if text_clean.startswith("iniciar"):
        parts = text.strip().split(" ", 1)
        company = parts[1] if len(parts) > 1 else "empresa não informada"

        discovery = create_discovery(company, channel_id, thread_ts)
        msg = f"🔍 [DISCOVERY] Discovery iniciado para *{company}*.\n\nCole o holerite em Markdown para começar a extração."
        post_message_to_slack(channel_id, msg, thread_ts)
        return ""

    # Comando: gerar
    if text_clean == "gerar":
        discovery = get_active_discovery(channel_id)
        if not discovery:
            msg = "❌ Nenhum discovery ativo neste canal. Use `iniciar [empresa]` para começar."
            post_message_to_slack(channel_id, msg, thread_ts)
            return ""

        rubricas = discovery.get("rubricas", [])
        if not rubricas:
            msg = "⚠️ [RISCO] Nenhuma rubrica classificada ainda. Cole um holerite primeiro."
            post_message_to_slack(channel_id, msg, thread_ts)
            return ""

        update_discovery(discovery["id"], {"status": "completed"})
        saved_thread_ts = discovery.get("thread_ts") or thread_ts
        format_blueprint(discovery, channel_id, saved_thread_ts)
        return ""

    # Verifica se há discovery ativo aguardando resposta
    discovery = get_active_discovery(channel_id)

    if discovery:
        saved_thread_ts = discovery.get("thread_ts") or thread_ts
        current_question = discovery.get("current_question")

        if current_question and discovery["status"] == "awaiting_response":
            handle_human_response(text, discovery, current_question, saved_thread_ts)
            return ""

        handle_payslip(text, discovery, saved_thread_ts)
        return ""

    msg = "ℹ️ Nenhum discovery ativo. Use `iniciar [empresa]` para começar."
    post_message_to_slack(channel_id, msg, thread_ts)
    return ""


def handle_payslip(payslip_text: str, discovery: dict, thread_ts: str = None) -> None:
    update_discovery(discovery["id"], {"status": "processing"})

    extracted = extract_payslip(payslip_text)
    rubricas = extracted.get("rubricas", [])

    classified = classify_all(rubricas)

    pending = [r for r in classified if r.get("confianca") == "baixa"]
    resolved = [r for r in classified if r.get("confianca") != "baixa"]

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

        msg = (
            f"🔍 [DISCOVERY] Extraí e classifiquei {len(classified)} rubricas para *{discovery['company']}*.\n"
            f"{len(resolved)} resolvidas automaticamente, {len(pending)} precisam de esclarecimento.\n\n"
            f"❓ [PERGUNTA] Sobre a rubrica *{first_question['nome']}*:\n"
            f"{first_question.get('observacao', 'Preciso de mais informações sobre esta rubrica.')}\n\n"
            f"Como ela é calculada e qual sua natureza (salarial ou indenizatória)?"
        )
        post_message_to_slack(discovery["channel_id"], msg, thread_ts)
        return

    updates["status"] = "classified"
    update_discovery(discovery["id"], updates)

    msg = (
        f"🔍 [DISCOVERY] Extraí e classifiquei {len(classified)} rubricas para *{discovery['company']}* com alta confiança.\n\n"
        f"Digite `gerar` para produzir a planta final."
    )
    post_message_to_slack(discovery["channel_id"], msg, thread_ts)


def handle_human_response(response_text: str, discovery: dict, current_question: dict, thread_ts: str = None) -> None:
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

        msg = (
            f"✅ Resposta registrada para *{current_question['nome']}*.\n\n"
            f"❓ [PERGUNTA] Sobre a rubrica *{next_question['nome']}*:\n"
            f"{next_question.get('observacao', 'Preciso de mais informações.')}\n\n"
            f"Como ela é calculada e qual sua natureza?"
        )
        post_message_to_slack(discovery["channel_id"], msg, thread_ts)
        return

    update_discovery(discovery["id"], {
        "rubricas": resolved,
        "current_question": None,
        "pending_questions": [],
        "status": "classified"
    })

    msg = "✅ Todas as rubricas esclarecidas.\n\nDigite `gerar` para produzir a planta final."
    post_message_to_slack(discovery["channel_id"], msg, thread_ts)


def format_blueprint(discovery: dict, channel_id: str, thread_ts: str = None) -> None:
    rubricas = discovery.get("rubricas", [])
    company = discovery.get("company", "")

    order_data = generate_calculation_order(rubricas)
    pdf_bytes = generate_blueprint_pdf(discovery, order_data)

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

    filename = f"planta_{company.lower().replace(' ', '_')}.pdf"
    upload_pdf_to_slack(pdf_bytes, filename, channel_id, summary, thread_ts)

    pendencias = [r for r in rubricas if r.get("confianca") != "alta"]
    if pendencias:
        linhas = ["⚠️ [PENDÊNCIAS] Rubricas que requerem atenção antes da migração:\n"]
        for r in pendencias:
            nivel = "Revisar" if r.get("confianca") == "media" else "Decidir"
            linhas.append(f"• *{r.get('nome')}* — {nivel}: {r.get('observacao', '')}")
        pendencias_msg = "\n".join(linhas)
    else:
        pendencias_msg = "✅ [PENDÊNCIAS] Sem pendências — todas as rubricas foram classificadas com alta confiança."

    post_message_to_slack(channel_id, pendencias_msg, thread_ts)