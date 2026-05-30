# supervisor.py

import json
from services.supabase_client import supabase
from agents.extractor import extract_payslip
from agents.legal import classify_all
from agents.blueprint import generate_calculation_order
from agents.interviewer import process_response
from services.pdf_generator import generate_blueprint_pdf
from services.slack_uploader import upload_pdf_to_slack, post_message_to_slack
from services.rag import index_document
from openai import OpenAI
import os

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


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
        "stage": "identification",
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
        msg = (
            f"🔍 [DISCOVERY] Discovery iniciado para *{company}*.\n\n"
            f"Antes de começar, preciso de algumas informações sobre a empresa.\n\n"
            f"Responda em texto livre:\n"
            f"• Número de funcionários CLT\n"
            f"• Sistema de folha atual (ex: Totvs, ADP, Domínio, planilha)\n"
            f"• Regime de trabalho (presencial / híbrido / remoto)\n"
            f"• Sindicato aplicável (ou \"não sindicalizado\")"
        )
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
            msg = "⚠️ [RISCO] Nenhuma rubrica classificada ainda. Complete as etapas anteriores primeiro."
            post_message_to_slack(channel_id, msg, thread_ts)
            return ""

        update_discovery(discovery["id"], {"status": "completed"})
        saved_thread_ts = discovery.get("thread_ts") or thread_ts
        format_blueprint(discovery, channel_id, saved_thread_ts)
        return ""

    # Verifica discovery ativo e roteia pelo stage
    discovery = get_active_discovery(channel_id)

    if not discovery:
        msg = "ℹ️ Nenhum discovery ativo. Use `iniciar [empresa]` para começar."
        post_message_to_slack(channel_id, msg, thread_ts)
        return ""

    saved_thread_ts = discovery.get("thread_ts") or thread_ts
    stage = discovery.get("stage", "identification")

    if stage == "identification":
        handle_identification(text, discovery, saved_thread_ts)
        return ""

    if stage == "cct":
        handle_cct(text, discovery, saved_thread_ts)
        return ""

    if stage == "payslip":
        pending = discovery.get("pending_questions", [])
        if pending and discovery["status"] == "awaiting_response":
            handle_human_response(text, discovery, pending, saved_thread_ts)
            return ""
        handle_payslip(text, discovery, saved_thread_ts)
        return ""

    msg = "ℹ️ Nenhum discovery ativo. Use `iniciar [empresa]` para começar."
    post_message_to_slack(channel_id, msg, thread_ts)
    return ""


def handle_identification(text: str, discovery: dict, thread_ts: str = None) -> None:
    """Extracts company info from free text and advances to CCT stage."""
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": """Você é um assistente que extrai informações de empresas a partir de texto livre.
Extraia as informações e retorne APENAS um JSON válido, sem texto adicional:
{
  "num_funcionarios": "número ou faixa informada, ou null se não informado",
  "sistema_folha": "sistema informado, ou null",
  "regime_trabalho": "presencial, híbrido, remoto ou null",
  "sindicato": "nome do sindicato ou 'não sindicalizado' ou null"
}"""
            },
            {
                "role": "user",
                "content": text
            }
        ],
        temperature=0
    )

    try:
        company_info = json.loads(response.choices[0].message.content)
    except Exception:
        company_info = {"texto_original": text}

    update_discovery(discovery["id"], {
        "company_info": company_info,
        "stage": "cct"
    })

    msg = (
        f"✅ Informações registradas.\n\n"
        f"Agora cole a CCT (Convenção Coletiva de Trabalho) aplicável à empresa em texto ou Markdown.\n\n"
        f"Se não tiver a CCT, digite `pular`."
    )
    post_message_to_slack(discovery["channel_id"], msg, thread_ts)


def handle_cct(text: str, discovery: dict, thread_ts: str = None) -> None:
    """Indexes CCT content and advances to payslip stage."""
    text_clean = text.strip().lower()

    if text_clean == "pular":
        update_discovery(discovery["id"], {
            "cct_content": None,
            "stage": "payslip"
        })
        msg = "⏭️ CCT pulada. Cole o holerite em Markdown para começar a extração."
        post_message_to_slack(discovery["channel_id"], msg, thread_ts)
        return

    company = discovery.get("company", "empresa")
    sindicato = (discovery.get("company_info") or {}).get("sindicato", "CCT")

    index_document(
        title=f"CCT — {sindicato} — {company}",
        source=f"CCT-{company}",
        content=text
    )

    update_discovery(discovery["id"], {
        "cct_content": text,
        "stage": "payslip"
    })

    msg = (
        f"✅ CCT indexada com sucesso.\n\n"
        f"Agora cole o holerite em Markdown para começar a extração."
    )
    post_message_to_slack(discovery["channel_id"], msg, thread_ts)


def handle_payslip(payslip_text: str, discovery: dict, thread_ts: str = None) -> None:
    update_discovery(discovery["id"], {"status": "processing"})

    extracted = extract_payslip(payslip_text)
    rubricas = extracted.get("rubricas", [])
    classified = classify_all(rubricas)

    pending = [r for r in classified if r.get("confianca") == "baixa"]
    resolved = [r for r in classified if r.get("confianca") != "baixa"]

    updates = {"rubricas": resolved}

    if pending:
        updates["status"] = "awaiting_response"
        updates["pending_questions"] = pending
        updates["current_question"] = None
        update_discovery(discovery["id"], updates)

        msg = (
            f"🔍 [DISCOVERY] Extraí e classifiquei {len(classified)} rubricas para *{discovery['company']}*.\n"
            f"{len(resolved)} classificadas com alta confiança. "
            f"{len(pending)} precisam de esclarecimento.\n\n"
            f"{_format_pending_message(pending)}\n\n"
            f"Responda sobre quantas quiser em uma ou mais mensagens. "
            f"Quando terminar, digite `gerar`."
        )
        post_message_to_slack(discovery["channel_id"], msg, thread_ts)
        return

    updates["status"] = "classified"
    updates["pending_questions"] = []
    updates["current_question"] = None
    update_discovery(discovery["id"], updates)

    msg = (
        f"🔍 [DISCOVERY] Extraí e classifiquei {len(classified)} rubricas para "
        f"*{discovery['company']}* com alta confiança.\n\n"
        f"Digite `gerar` para produzir a planta final."
    )
    post_message_to_slack(discovery["channel_id"], msg, thread_ts)


def handle_human_response(response_text: str, discovery: dict, pending: list, thread_ts: str = None) -> None:
    result = process_response(response_text, pending)

    closed = result["closed"]
    still_pending = result["still_pending"]

    resolved = discovery.get("rubricas", []) + closed

    if still_pending:
        update_discovery(discovery["id"], {
            "rubricas": resolved,
            "pending_questions": still_pending,
            "status": "awaiting_response"
        })

        closed_names = [r["nome"] for r in closed]
        closed_text = (
            f"✅ Esclarecidas: {', '.join(closed_names)}\n\n"
            if closed_names else ""
        )

        msg = (
            f"{closed_text}"
            f"❓ [PENDÊNCIAS RESTANTES] Ainda preciso de esclarecimento sobre:\n\n"
            f"{_format_pending_message(still_pending)}\n\n"
            f"Responda sobre quantas quiser, ou digite `gerar` para fechar com as pendências marcadas."
        )
        post_message_to_slack(discovery["channel_id"], msg, thread_ts)
        return

    update_discovery(discovery["id"], {
        "rubricas": resolved,
        "pending_questions": [],
        "current_question": None,
        "status": "classified"
    })

    msg = "✅ Todas as rubricas esclarecidas.\n\nDigite `gerar` para produzir a planta final."
    post_message_to_slack(discovery["channel_id"], msg, thread_ts)


def _format_pending_message(pending: list) -> str:
    lines = ["❓ [PERGUNTAS] Preciso de esclarecimento sobre as seguintes rubricas:\n"]
    for i, r in enumerate(pending, 1):
        lines.append(
            f"*{i}. {r['nome']}*\n"
            f"{r.get('observacao', 'Preciso de mais informações sobre esta rubrica.')}\n"
        )
    return "\n".join(lines)


def format_blueprint(discovery: dict, channel_id: str, thread_ts: str = None) -> None:
    rubricas = discovery.get("rubricas", [])
    company = discovery.get("company", "")

    order_data = generate_calculation_order(rubricas)
    pdf_bytes = generate_blueprint_pdf(discovery, order_data)

    total = len(rubricas)
    alta = len([r for r in rubricas if r.get("confianca") == "alta"])
    media = len([r for r in rubricas if r.get("confianca") == "media"])
    baixa = len([r for r in rubricas if r.get("confianca") == "baixa"])

    pendencias = [r for r in rubricas if r.get("confianca") != "alta"]
    if pendencias:
        linhas = ["⚠️ [PENDÊNCIAS] Rubricas que requerem atenção antes da migração:\n"]
        for r in pendencias:
            nivel = "Revisar" if r.get("confianca") == "media" else "Decidir"
            linhas.append(f"• *{r.get('nome')}* — {nivel}: {r.get('observacao', '')}")
        pendencias_msg = "\n".join(linhas)
    else:
        pendencias_msg = "✅ [PENDÊNCIAS] Sem pendências — todas as rubricas foram classificadas com alta confiança."

    summary = (
        f"✅ [PLANTA] Discovery concluído — *{company}*\n"
        f"Total de rubricas: {total} | "
        f"✅ {alta} confirmadas | "
        f"⚠️ {media} revisar | "
        f"❌ {baixa} requer decisão\n"
        f"Planta completa em anexo."
        f"{pendencias_msg}"
    )

    filename = f"planta_{company.lower().replace(' ', '_')}.pdf"
    upload_pdf_to_slack(pdf_bytes, filename, channel_id, summary, thread_ts)