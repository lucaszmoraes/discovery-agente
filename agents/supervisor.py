# supervisor.py

import json
import os
import base64
from openai import OpenAI
from services.supabase_client import supabase
from agents.extractor import extract_payslip, AGENT as EXTRACTOR
from agents.legal import classify_all
from agents.blueprint import generate_calculation_order, AGENT as BLUEPRINT
from agents.interviewer import process_response, AGENT as INTERVIEWER
from services.pdf_generator import generate_blueprint_pdf
from services.pdf_reader import extract_text_from_pdf_b64, extract_text_from_multiple_pdfs
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
- "respond": responder diretamente ao usuário sem acionar agente (para dúvidas, comandos inválidos, mensagens fora de contexto)

REGRAS DE DECISÃO:
1. Se stage = "identification" → "identification" para extrair dados da empresa
2. Se stage = "payslip" e não há rubricas ainda → "extractor"
3. Se stage = "payslip" e há rubricas pendentes → "interviewer"
4. Se o usuário disse "gerar" ou "continuar" e há rubricas classificadas → "blueprint"
5. Em caso de dúvida → "respond"

Retorne APENAS um JSON válido, sem texto adicional:
{{
  "action": "extractor" | "interviewer" | "blueprint" | "identification" | "respond",
  "justificativa": "por que você escolheu essa ação",
  "mensagem_direta": "mensagem para o usuário — preencha APENAS se action = respond, caso contrário null"
}}"""

CONVERSATIONAL_SYSTEM_PROMPT = """Você é o assistente do Discovery Agêntico — um sistema que automatiza o mapeamento de folha de pagamento para empresas que estão migrando para a Tako, uma plataforma de payroll.

Seu papel é conversar de forma natural, clara e prestativa com o usuário — que normalmente é um profissional de RH ou DP (Departamento Pessoal) da empresa cliente.

CONTEXTO DO SISTEMA:
- O sistema coleta informações sobre a empresa e seus holerites
- Analisa as rubricas (verbas) da folha de pagamento
- Classifica cada rubrica com base na legislação trabalhista brasileira (CLT, INSS, IRRF, FGTS)
- Gera uma "planta de cálculo" — documento que mostra como cada rubrica é calculada, suas dependências e base legal
- O objetivo é garantir que a migração da folha para a Tako seja feita sem erros

GLOSSÁRIO (use para explicar termos quando perguntado):
- CCT (Convenção Coletiva de Trabalho): acordo entre sindicato e empresas que define regras específicas da categoria (pisos salariais, benefícios, adicionais). Complementa a CLT.
- Rubrica: cada linha do holerite (ex: salário base, INSS, vale transporte)
- Natureza salarial vs indenizatória: rubricas salariais integram o salário e têm reflexos em FGTS, férias, 13º. Indenizatórias não.
- Planta de cálculo: mapa completo da folha — fórmulas, dependências, ordem de cálculo
- Discovery: processo de mapeamento da folha antes da migração

ESTADO ATUAL DO DISCOVERY:
{state_summary}

REGRAS DE COMPORTAMENTO:
- Responda em português, de forma direta e amigável
- Explique termos técnicos quando o usuário demonstrar dúvida
- Se o usuário estiver confuso sobre o que o sistema precisa, explique com clareza e empatia
- Se o discovery já foi concluído (stage = done), explique o que foi feito e o que o usuário pode fazer com o resultado
- Nunca invente informações sobre legislação — se não tiver certeza, diga que é necessário verificar com um especialista
- Seja conciso — respostas curtas e diretas são melhores que parágrafos longos"""


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Orquestração LLM
# ---------------------------------------------------------------------------

def orchestrate(text: str, discovery: dict | None) -> dict:
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


def _responder_naturalmente(texto: str, discovery: dict | None) -> str:
    """Usa o LLM para responder ao usuário de forma natural com contexto do discovery."""
    state_summary = "Nenhum discovery ativo ainda."
    if discovery:
        rubricas = discovery.get("rubricas") or []
        pending = discovery.get("pending_questions") or []
        cct_enviada = discovery.get("cct_enviada", False)
        stage = discovery.get("stage", "")

        stage_labels = {
            "identification": "coletando informações da empresa",
            "cct": "aguardando CCT",
            "payslip": "aguardando holerites",
            "review_inputs": "revisando inputs recebidos",
            "interviewing": "esclarecendo rubricas ambíguas",
            "ready": "pronto para gerar a planta",
            "done": "discovery concluído"
        }

        state_summary = f"""Empresa: {discovery.get('company', 'não informada')}
Etapa atual: {stage_labels.get(stage, stage)}
CCT enviada: {'sim' if cct_enviada else 'não'}
Rubricas classificadas: {len(rubricas)}
Rubricas pendentes de esclarecimento: {len(pending)}"""

    system_prompt = CONVERSATIONAL_SYSTEM_PROMPT.format(state_summary=state_summary)

    messages = [{"role": "system", "content": system_prompt}]

    history = (discovery.get("conversation_history") or []) if discovery else []
    for msg in history[-10:]:  # últimas 10 mensagens para não explodir o contexto
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": texto})

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        temperature=0.4
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Rota Slack (legado — mantida intacta)
# ---------------------------------------------------------------------------

def handle_message(text: str, channel_id: str, thread_ts: str = None) -> str:
    text_clean = text.strip().lower()

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
        discovery = get_active_discovery(channel_id)

    saved_thread_ts = discovery.get("thread_ts") if discovery else thread_ts
    decision = orchestrate(text, discovery)
    action = decision.get("action")

    if action == "identification":
        handle_identification(text, discovery, saved_thread_ts)
    elif action == "extractor":
        handle_payslip(text, discovery, saved_thread_ts)
    elif action == "interviewer":
        pending = discovery.get("pending_questions", [])
        handle_human_response(text, discovery, pending, saved_thread_ts)
    elif action == "blueprint":
        update_discovery(discovery["id"], {"status": "completed"})
        format_blueprint(discovery, channel_id, saved_thread_ts)
    else:
        msg = decision.get("mensagem_direta") or "ℹ️ Nenhum discovery ativo."
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
                "content": """Extraia informações da empresa e retorne APENAS JSON válido:
{
  "nome_empresa": "nome da empresa ou null",
  "num_funcionarios": "número ou null",
  "sistema_folha": "sistema ou null",
  "regime_trabalho": "presencial/híbrido/remoto ou null",
  "sindicato": "nome ou 'não sindicalizado' ou null"
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

    nome_empresa = company_info.get("nome_empresa") or discovery.get("company", "nova empresa")
    update_discovery(discovery["id"], {
        "company": nome_empresa,
        "company_info": company_info,
        "stage": "cct"
    })
    msg = "✅ Informações registradas.\n\nAgora cole a CCT ou digite `pular`."
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
    msg = "✅ CCT indexada.\n\nAgora cole o holerite em Markdown para começar a extração."
    reply(discovery, msg, thread_ts)


def handle_payslip(payslip_text: str, discovery: dict, thread_ts: str = None) -> None:
    update_discovery(discovery["id"], {"status": "processing"})
    extracted = extract_payslip(payslip_text)
    rubricas = extracted.get("rubricas", [])
    classified = classify_all(rubricas)

    pending = [r for r in classified if r.get("confianca") == "baixa"]
    resolved = [r for r in classified if r.get("confianca") != "baixa"]

    if pending:
        update_discovery(discovery["id"], {
            "rubricas": resolved,
            "status": "awaiting_response",
            "pending_questions": pending,
            "current_question": None
        })
        msg = (
            f"🔍 Extraí {len(classified)} rubricas. "
            f"{len(resolved)} classificadas, {len(pending)} precisam de esclarecimento.\n\n"
            f"{_format_pending_message(pending)}\n\n"
            f"Responda ou digite `gerar`."
        )
        reply(discovery, msg, thread_ts)
        return

    update_discovery(discovery["id"], {
        "rubricas": classified,
        "status": "classified",
        "pending_questions": [],
        "current_question": None
    })
    msg = f"🔍 {len(classified)} rubricas classificadas.\n\nDigite `gerar` para produzir a planta."
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
            f"{closed_text}❓ Ainda preciso de esclarecimento:\n\n"
            f"{_format_pending_message(still_pending)}\n\n"
            f"Responda ou digite `gerar`."
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
    lines = ["❓ Preciso de esclarecimento sobre as seguintes rubricas:\n"]
    for i, r in enumerate(pending, 1):
        lines.append(
            f"**{i}. {r['nome']}**\n"
            f"{r.get('observacao', 'Preciso de mais informações.')}\n"
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
        linhas = ["⚠️ Rubricas que requerem atenção:\n"]
        for r in pendencias:
            nivel = "Revisar" if r.get("confianca") == "media" else "Decidir"
            linhas.append(f"• *{r.get('nome')}* — {nivel}: {r.get('observacao', '')}")
        pendencias_msg = "\n".join(linhas)
    else:
        pendencias_msg = "✅ Sem pendências."

    summary = (
        f"✅ Discovery concluído — *{company}*\n"
        f"Total: {total} | ✅ {alta} confirmadas | ⚠️ {media} revisar | ❌ {baixa} decidir\n"
        f"{pendencias_msg}"
    )
    filename = f"planta_{company.lower().replace(' ', '_')}.pdf"
    upload_pdf_to_slack(pdf_bytes, filename, channel_id, summary, thread_ts)


# ---------------------------------------------------------------------------
# Rota Streamlit
# ---------------------------------------------------------------------------

def _run_identification(texto: str, discovery: dict) -> str:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": """Extraia informações da empresa e retorne APENAS JSON válido:
{
  "nome_empresa": "nome da empresa ou null",
  "num_funcionarios": "número ou null",
  "sistema_folha": "sistema ou null",
  "regime_trabalho": "presencial/híbrido/remoto ou null",
  "sindicato": "nome ou 'não sindicalizado' ou null"
}"""
            },
            {"role": "user", "content": texto}
        ],
        temperature=0
    )
    try:
        company_info = json.loads(response.choices[0].message.content)
    except Exception:
        company_info = {"texto_original": texto}

    nome_empresa = company_info.get("nome_empresa") or discovery.get("company", "nova empresa")
    update_discovery(discovery["id"], {
        "company": nome_empresa,
        "company_info": company_info,
        "stage": "cct"
    })

    return (
        f"✅ Tudo certo, registrei as informações da **{nome_empresa}**.\n\n"
        f"Agora, se você tiver a CCT (Convenção Coletiva de Trabalho) da empresa, pode enviá-la em PDF — "
        f"ela me ajuda a classificar as rubricas com mais precisão. Se não tiver ou quiser pular, clique em **Pular CCT**."
    )


def _run_cct_pdf(pdf_b64: str, discovery: dict) -> str:
    texto = extract_text_from_pdf_b64(pdf_b64)
    company = discovery.get("company", "empresa")
    sindicato = (discovery.get("company_info") or {}).get("sindicato", "CCT")
    index_document(
        title=f"CCT — {sindicato} — {company}",
        source=f"CCT-{company}",
        content=texto
    )
    update_discovery(discovery["id"], {
        "cct_content": texto,
        "cct_enviada": True,
        "stage": "payslip"
    })
    return (
        "✅ CCT indexada com sucesso — vou usar as regras dela para classificar as rubricas.\n\n"
        "Agora envie os holerites em PDF. Pode selecionar mais de um arquivo."
    )


def _run_holerites_pdf(pdfs_b64: list, discovery: dict) -> str:
    texto = extract_text_from_multiple_pdfs(pdfs_b64)
    update_discovery(discovery["id"], {
        "payslip_content": texto,
        "num_holerites": len(pdfs_b64),
        "stage": "review_inputs"
    })
    cct_enviada = discovery.get("cct_enviada", False)
    cct_status = "✅ Enviada" if cct_enviada else "⏳ Pendente"

    aviso_cct = (
        "\n\n⚠️ A CCT ainda não foi enviada. Você pode enviá-la agora para uma análise mais completa, "
        "ou clicar em **Continuar** para prosseguir sem ela."
    ) if not cct_enviada else ""

    return (
        f"📋 **Inputs recebidos:**\n\n"
        f"- Empresa: ✅ {discovery.get('company')}\n"
        f"- CCT: {cct_status}\n"
        f"- Holerites: ✅ {len(pdfs_b64)} arquivo(s)\n"
        f"{aviso_cct}\n\n"
        f"Quando quiser prosseguir com a análise, clique em **Continuar**."
    )


def _run_extractor(discovery: dict) -> str:
    texto = discovery.get("payslip_content", "")
    update_discovery(discovery["id"], {"status": "processing"})
    extracted = extract_payslip(texto)
    rubricas = extracted.get("rubricas", [])
    classified = classify_all(rubricas)

    pending = [r for r in classified if r.get("confianca") == "baixa"]
    resolved = [r for r in classified if r.get("confianca") != "baixa"]

    if pending:
        update_discovery(discovery["id"], {
            "rubricas": resolved,
            "status": "awaiting_response",
            "pending_questions": pending,
            "current_question": None,
            "stage": "interviewing"
        })
        return (
            f"🔍 Analisei os holerites e encontrei **{len(classified)} rubricas**. "
            f"{len(resolved)} já estão classificadas com segurança.\n\n"
            f"Preciso de mais informações sobre {len(pending)} rubrica(s) antes de fechar a planta:\n\n"
            f"{_format_pending_message(pending)}\n\n"
            f"Responda o que souber — não precisa ser técnico, pode ser em linguagem livre. "
            f"Se preferir pular, clique em **Pular perguntas** e gero a planta com essas lacunas marcadas."
        )

    update_discovery(discovery["id"], {
        "rubricas": classified,
        "status": "classified",
        "pending_questions": [],
        "current_question": None,
        "stage": "ready"
    })
    return (
        f"🔍 Ótimo! Analisei os holerites e classifiquei **{len(classified)} rubricas** com alta confiança.\n\n"
        f"Clique em **Gerar blueprint** para produzir a planta de cálculo completa."
    )


def _run_interviewer(texto: str, discovery: dict, pending: list) -> str:
    history = discovery.get("conversation_history") or []
    result = process_response(texto, pending, history)
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
        return (
            f"{closed_text}"
            f"Ainda preciso de algumas informações:\n\n"
            f"{_format_pending_message(still_pending)}\n\n"
            f"Responda o que souber, ou clique em **Pular perguntas** para gerar com as lacunas marcadas."
        )

    update_discovery(discovery["id"], {
        "rubricas": resolved,
        "pending_questions": [],
        "current_question": None,
        "status": "classified",
        "stage": "ready"
    })
    return "✅ Perfeito! Todas as rubricas estão esclarecidas.\n\nClique em **Gerar blueprint** para produzir a planta."


def _run_blueprint(discovery: dict) -> dict:
    rubricas = discovery.get("rubricas", [])

    pending = discovery.get("pending_questions", [])
    if pending:
        for r in pending:
            r["observacao"] = (r.get("observacao") or "") + " | Pendência assumida por precaução — tratar como salarial."
        rubricas = rubricas + pending
        update_discovery(discovery["id"], {
            "rubricas": rubricas,
            "pending_questions": []
        })

    company = discovery.get("company", "")
    order_data = generate_calculation_order(rubricas)
    pdf_bytes = generate_blueprint_pdf(discovery, order_data)
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    total = len(rubricas)
    alta = len([r for r in rubricas if r.get("confianca") == "alta"])
    media = len([r for r in rubricas if r.get("confianca") == "media"])
    baixa = len([r for r in rubricas if r.get("confianca") == "baixa"])

    pendencias = [r for r in rubricas if r.get("confianca") != "alta"]
    if pendencias:
        linhas = ["⚠️ **Rubricas que requerem atenção antes da migração:**\n"]
        for r in pendencias:
            nivel = "Revisar" if r.get("confianca") == "media" else "Decidir"
            linhas.append(f"- **{r.get('nome')}** — {nivel}: {r.get('observacao', '')}")
        pendencias_texto = "\n".join(linhas)
    else:
        pendencias_texto = "✅ Sem pendências — todas as rubricas classificadas com alta confiança."

    mensagem = (
        f"✅ **Planta de cálculo gerada — {company}**\n\n"
        f"Total: {total} rubricas | ✅ {alta} confirmadas | "
        f"⚠️ {media} revisar | ❌ {baixa} requer decisão\n\n"
        f"{pendencias_texto}\n\n"
        f"📄 O PDF com a planta completa está disponível para download abaixo."
    )

    update_discovery(discovery["id"], {"stage": "done"})

    return {
        "mensagem": mensagem,
        "pdf_b64": pdf_b64,
        "pdf_filename": f"planta_{company.lower().replace(' ', '_')}.pdf"
    }


# ---------------------------------------------------------------------------
# Entry point Streamlit
# ---------------------------------------------------------------------------

def handle_streamlit_message(
    texto: str,
    discovery_id: str = None,
    pdfs_b64: list = None,
    tipo_pdf: str = None
) -> dict:

    if discovery_id:
        result = supabase.table("discoveries")\
            .select("*")\
            .eq("id", discovery_id)\
            .limit(1)\
            .execute()
        discovery = result.data[0] if result.data else None
    else:
        discovery = None

    stage = discovery.get("stage") if discovery else None

    # Upload de CCT via PDF
    if pdfs_b64 and tipo_pdf == "cct" and discovery:
        resposta = _run_cct_pdf(pdfs_b64[0], discovery)
        append_to_history(discovery, "assistant", resposta)
        return {"mensagem": resposta, "discovery_id": discovery["id"]}

    # Upload de holerites via PDF
    if pdfs_b64 and tipo_pdf == "holerite" and discovery:
        resposta = _run_holerites_pdf(pdfs_b64, discovery)
        append_to_history(discovery, "assistant", resposta)
        return {"mensagem": resposta, "discovery_id": discovery["id"]}

    # Iniciar análise
    if texto.strip().lower() in ["iniciar análise", "iniciar analise", "iniciar"]:
        discovery = create_discovery("nova empresa", channel_id="streamlit")
        msg = (
            "👋 Olá! Sou o assistente de discovery da Tako.\n\n"
            "Vou te ajudar a mapear a folha de pagamento da empresa antes da migração — "
            "identificando cada rubrica, como ela é calculada e o que diz a lei sobre ela.\n\n"
            "Para começar, me conta sobre a empresa:\n\n"
            "- Nome da empresa\n"
            "- Número de funcionários CLT\n"
            "- Sistema de folha atual (ex: Totvs, ADP, Domínio, planilha)\n"
            "- Regime de trabalho (presencial / híbrido / remoto)\n"
            "- Sindicato aplicável (ou \"não sindicalizado\")"
        )
        append_to_history(discovery, "assistant", msg)
        return {"mensagem": msg, "discovery_id": discovery["id"]}

    # Sem discovery ativo
    if not discovery:
        return {
            "mensagem": "Clique em **Iniciar análise** para começar.",
            "discovery_id": None
        }

    # Registra mensagem e recarrega
    append_to_history(discovery, "user", texto)
    discovery = supabase.table("discoveries")\
        .select("*")\
        .eq("id", discovery["id"])\
        .limit(1)\
        .execute().data[0]

    stage = discovery.get("stage")

    # Stage: identification
    if stage == "identification":
        resposta = _run_identification(texto, discovery)
        append_to_history(discovery, "assistant", resposta)
        return {"mensagem": resposta, "discovery_id": discovery["id"]}

    # Stage: cct — pular via texto
    if stage == "cct" and texto.strip().lower() in ["pular", "pular cct", "skip"]:
        update_discovery(discovery["id"], {"cct_enviada": False, "stage": "payslip"})
        resposta = (
            "⏭️ Sem problema, vamos seguir sem a CCT.\n\n"
            "Agora envie os holerites em PDF — pode selecionar mais de um arquivo de uma vez."
        )
        append_to_history(discovery, "assistant", resposta)
        return {"mensagem": resposta, "discovery_id": discovery["id"]}

    # Stage: cct — mensagem fora do fluxo (dúvidas sobre CCT etc)
    if stage == "cct":
        resposta = _responder_naturalmente(texto, discovery)
        append_to_history(discovery, "assistant", resposta)
        return {"mensagem": resposta, "discovery_id": discovery["id"]}

    # Stage: review_inputs — continuar
    if stage == "review_inputs" and texto.strip().lower() in ["continuar", "gerar", "processar"]:
        resposta = _run_extractor(discovery)
        append_to_history(discovery, "assistant", resposta)
        return {"mensagem": resposta, "discovery_id": discovery["id"]}

    # Stage: review_inputs — qualquer outra mensagem
    if stage == "review_inputs":
        resposta = _responder_naturalmente(texto, discovery)
        append_to_history(discovery, "assistant", resposta)
        return {"mensagem": resposta, "discovery_id": discovery["id"]}

    # Stage: interviewing — pular
    if stage == "interviewing" and texto.strip().lower() in ["pular", "gerar"]:
        update_discovery(discovery["id"], {"status": "completed"})
        resultado = _run_blueprint(discovery)
        append_to_history(discovery, "assistant", resultado["mensagem"])
        return {
            "mensagem": resultado["mensagem"],
            "discovery_id": discovery["id"],
            "pdf_b64": resultado["pdf_b64"],
            "pdf_filename": resultado["pdf_filename"]
        }

    # Stage: interviewing — resposta ou dúvida
    if stage == "interviewing":
        pending = discovery.get("pending_questions", [])
        # Tenta interpretar como resposta às rubricas
        resposta = _run_interviewer(texto, discovery, pending)
        append_to_history(discovery, "assistant", resposta)
        return {"mensagem": resposta, "discovery_id": discovery["id"]}

    # Stage: ready
    if stage == "ready":
        update_discovery(discovery["id"], {"status": "completed"})
        resultado = _run_blueprint(discovery)
        append_to_history(discovery, "assistant", resultado["mensagem"])
        return {
            "mensagem": resultado["mensagem"],
            "discovery_id": discovery["id"],
            "pdf_b64": resultado["pdf_b64"],
            "pdf_filename": resultado["pdf_filename"]
        }

    # Stage: done ou qualquer outro — conversa natural
    resposta = _responder_naturalmente(texto, discovery)
    append_to_history(discovery, "assistant", resposta)
    return {"mensagem": resposta, "discovery_id": discovery["id"]}