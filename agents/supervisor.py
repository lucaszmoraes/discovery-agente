# supervisor.py

import json
import os
from openai import OpenAI
from services.supabase_client import supabase
from agents.extractor import extract_payslip, AGENT as EXTRACTOR
from agents.legal import classify_all
from agents.blueprint import generate_calculation_order, AGENT as BLUEPRINT
from agents.interviewer import process_response, AGENT as INTERVIEWER
from services.pdf_generator import generate_blueprint_pdf
from services.slack_uploader import upload_pdf_to_slack, post_message_to_slack
from services.rag import index_document

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

SUPERVISOR_SYSTEM_PROMPT = """Você é o orquestrador de um sistema de discovery de folha de pagamento.
Seu papel é analisar o histórico da conversa e o estado atual do discovery para decidir qual ação tomar.

AGENTES DISPONÍVEIS:
- "extractor": {extractor_desc}
- "interviewer": {interviewer_desc}
- "blueprint": {blueprint_desc}
- "identification": coletar informações básicas da empresa (funcionários, sistema de folha, regime de trabalho, sindicato)
- "cct": receber e indexar a CCT (Convenção Coletiva de Trabalho) da empresa
- "respond": responder diretamente ao usuário sem acionar agente (para dúvidas, comandos inválidos, mensagens fora de contexto)

REGRAS DE DECISÃO:
1. Se não há discovery ativo e o usuário não usou "iniciar [empresa]" → "respond" orientando o usuário
2. Se stage = "identification" → "identification" para extrair dados da empresa
3. Se stage = "cct" → "cct" para receber a CCT (ou pular)
4. Se stage = "payslip" e não há rubricas ainda → "extractor" se o usuário colou um holerite
5. Se stage = "payslip" e há rubricas pendentes → "interviewer" se o usuário enviou uma resposta sobre as rubricas
6. Se o usuário disse "gerar" e há rubricas classificadas → "blueprint"
7. Se o usuário disse "gerar" mas não há rubricas → "respond" orientando a colar um holerite primeiro
8. Em caso de dúvida → "respond"

Retorne APENAS um JSON válido, sem texto adicional:
{{
  "action": "extractor" | "interviewer" | "blueprint" | "identification" | "cct" | "respond",
  "justificativa": "por que você escolheu essa ação",
  "mensagem_direta": "mensagem para o usuário — preencha APENAS se action = respond, caso contrário null"
}}"""


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
        "thread_ts": thread_ts,
        "conversation_history": []
    }).execute()
    return result.data[0]


def update_discovery(discovery_id: str, updates: dict):
    supabase.table("discoveries")\
        .update(updates)\
        .eq("id", discovery_id)\
        .execute()


def append_to_history(discovery: dict, role: str, content: str) -> list:
    history = discovery.get("conversation_history") or []
    history.append({"role": role, "content": content})
    update_discovery(discovery["id"], {"conversation_history": history})
    return history


def reply(discovery: dict, msg: str, thread_ts: str = None) -> None:
    post_message_to_slack(discovery["channel_id"], msg, thread_ts)
    append_to_history(discovery, "assistant", msg)


def orchestrate(text: str, discovery: dict | None) -> dict:
    """Calls the LLM to decide which agent to activate."""
    system_prompt = SUPERVISOR_SYSTEM_PROMPT.format(
        extractor_desc=EXTRACTOR["description"],
        interviewer_desc=INTERVIEWER["description"],
        blueprint_desc=BLUEPRINT["description"]
    )

    state_summary = "Nenhum discovery ativo."
    if discovery:
        state_summary = f"""Discovery ativo: {discovery.get('company')}
Stage: {discovery.get('stage')}
Status: {discovery.get('status')}
Rubricas classificadas: {len(discovery.get('rubricas') or [])}
Rubricas pendentes: {len(discovery.get('pending_questions') or [])}"""

    messages = [{"role": "system", "content": system_prompt}]

    history = (discovery.get("conversation_history") or []) if discovery else []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({
        "role": "user",
        "content": f"""Estado atual:
{state_summary}

Nova mensagem do usuário:
{text}

Qual ação devo tomar?"""
    })

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        temperature=0
    )

    return json.loads(response.choices[0].message.content)


def handle_message(text: str, channel_id: str, thread_ts: str = None) -> str:
    text_clean = text.strip().lower()

    # Comando iniciar — único tratado antes da orquestração
    if text_clean.startswith("iniciar"):
        parts = text.strip().split(" ", 1)
        company = parts[1] if len(parts) > 1 else "empresa não informada"
        discovery = create_discovery(company, channel_id, thread_ts)
        append_to_history(discovery, "user", text)
        msg = (
            f"🔍 [DISCOVERY] Discovery iniciado para *{company}*.\n\n"
            f"Antes de começar, preciso de algumas informações sobre a empresa.\n\n"
            f"Responda em texto livre:\n"
            f"• Número de funcionários CLT\n"
            f"• Sistema de folha atual (ex: Totvs, ADP, Domínio, planilha)\n"
            f"• Regime de trabalho (presencial / híbrido / remoto)\n"
            f"• Sindicato aplicável (ou \"não sindicalizado\")"
        )
        reply(discovery, msg, thread_ts)
        return ""

    discovery = get_active_discovery(channel_id)

    if discovery:
        append_to_history(discovery, "user", text)
        # Recarrega discovery com histórico atualizado
        discovery = get_active_discovery(channel_id)

    saved_thread_ts = discovery.get("thread_ts") if discovery else thread_ts

    # LLM decide qual agente acionar
    decision = orchestrate(text, discovery)
    action = decision.get("action")

    if action == "identification":
        handle_identification(text, discovery, saved_thread_ts)

    elif action == "cct":
        handle_cct(text, discovery, saved_thread_ts)

    elif action == "extractor":
        handle_payslip(text, discovery, saved_thread_ts)

    elif action == "interviewer":
        pending = discovery.get("pending_questions", [])
        handle_human_response(text, discovery, pending, saved_thread_ts)

    elif action == "blueprint":
        update_discovery(discovery["id"], {"status": "completed"})
        format_blueprint(discovery, channel_id, saved_thread_ts)

    else:  # respond
        msg = decision.get("mensagem_direta") or "ℹ️ Nenhum discovery ativo. Use `iniciar [empresa]` para começar."
        if discovery:
            reply(discovery, msg, saved_thread_ts)
        else:
            post_message_to_slack(channel_id, msg, thread_ts)

    return ""


def handle_identification(text: str, discovery: dict, thread_ts: str = None) -> None:
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
            {"role": "user", "content": text}
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
    reply(discovery, msg, thread_ts)


def handle_cct(text: str, discovery: dict, thread_ts: str = None) -> None:
    if text.strip().lower() == "pular":
        update_discovery(discovery["id"], {"cct_content": None, "stage": "payslip"})
        msg = "⏭️ CCT pulada. Cole o holerite em Markdown para começar a extração."
        reply(discovery, msg, thread_ts)
        return

    company = discovery.get("company", "empresa")
    sindicato = (discovery.get("company_info") or {}).get("sindicato", "CCT")

    index_document(
        title=f"CCT — {sindicato} — {company}",
        source=f"CCT-{company}",
        content=text
    )

    update_discovery(discovery["id"], {"cct_content": text, "stage": "payslip"})
    msg = "✅ CCT indexada com sucesso.\n\nAgora cole o holerite em Markdown para começar a extração."
    reply(discovery, msg, thread_ts)


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
        reply(discovery, msg, thread_ts)
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
    reply(discovery, msg, thread_ts)


def handle_human_response(response_text: str, discovery: dict, pending: list, thread_ts: str = None) -> None:
    history = discovery.get("conversation_history") or []
    result = process_response(response_text, pending, history)

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
        closed_text = f"✅ Esclarecidas: {', '.join(closed_names)}\n\n" if closed_names else ""

        msg = (
            f"{closed_text}"
            f"❓ [PENDÊNCIAS RESTANTES] Ainda preciso de esclarecimento sobre:\n\n"
            f"{_format_pending_message(still_pending)}\n\n"
            f"Responda sobre quantas quiser, ou digite `gerar` para fechar com as pendências marcadas."
        )
        reply(discovery, msg, thread_ts)
        return

    update_discovery(discovery["id"], {
        "rubricas": resolved,
        "pending_questions": [],
        "current_question": None,
        "status": "classified"
    })

    msg = "✅ Todas as rubricas esclarecidas.\n\nDigite `gerar` para produzir a planta final."
    reply(discovery, msg, thread_ts)


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