# streamlit_app.py

import streamlit as st
import requests
import base64
import os

def scroll_to_bottom():
    st.components.v1.html(
        """
        <style>
            iframe { display: none; }
        </style>
        <script>
            setTimeout(function() {
                var container = window.parent.document.querySelector('section.stMain');
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            }, 300);
        </script>
        """,
        height=0
    )

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Discovery Agêntico",
    page_icon="🔍",
    layout="centered"
)

# ---------------------------------------------------------------------------
# Estado da sessão
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "discovery_id" not in st.session_state:
    st.session_state.discovery_id = None

if "pdf_data" not in st.session_state:
    st.session_state.pdf_data = None

if "pdf_filename" not in st.session_state:
    st.session_state.pdf_filename = None

if "iniciado" not in st.session_state:
    st.session_state.iniciado = False


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def send_message(texto: str, pdfs_b64: list = None, tipo_pdf: str = None) -> dict:
    try:
        payload = {
            "texto": texto,
            "discovery_id": st.session_state.discovery_id,
            "pdfs_b64": pdfs_b64,
            "tipo_pdf": tipo_pdf
        }
        response = requests.post(
            f"{BACKEND_URL}/streamlit/mensagem",
            json=payload,
            timeout=120
        )
        return response.json()
    except requests.exceptions.Timeout:
        return {"mensagem": "⚠️ O processamento demorou mais que o esperado. Tente novamente.", "discovery_id": st.session_state.discovery_id}
    except Exception as e:
        return {"mensagem": f"⚠️ Erro ao conectar ao servidor: {str(e)}", "discovery_id": st.session_state.discovery_id}


def process_backend_response(result: dict) -> str:
    if result.get("discovery_id"):
        st.session_state.discovery_id = result["discovery_id"]
    if result.get("pdf_b64"):
        st.session_state.pdf_data = base64.b64decode(result["pdf_b64"])
        st.session_state.pdf_filename = result.get("pdf_filename", "planta.pdf")
    return result.get("mensagem", "")


def add_message(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content})


def get_stage() -> str | None:
    if not st.session_state.discovery_id:
        return None
    try:
        response = requests.get(
            f"{BACKEND_URL}/discovery/{st.session_state.discovery_id}/stage",
            timeout=10
        )
        return response.json().get("stage")
    except Exception:
        return None


def files_to_b64(uploaded_files) -> list:
    result = []
    for f in uploaded_files:
        result.append(base64.b64encode(f.read()).decode("utf-8"))
    return result


# ---------------------------------------------------------------------------
# Tela inicial
# ---------------------------------------------------------------------------

st.title("🔍 Discovery Agêntico")
st.caption("Mapeamento automatizado de folha de pagamento")

if not st.session_state.iniciado:
    st.markdown("---")
    st.markdown("### Bem-vindo")
    st.markdown(
        "Este sistema analisa a folha de pagamento de uma empresa e gera a **planta de cálculo completa** — "
        "com rubricas, fórmulas, dependências e base legal — em minutos."
    )
    st.markdown(" ")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("▶️ Iniciar análise", use_container_width=True, type="primary"):
            with st.spinner("Iniciando..."):
                result = send_message("iniciar análise")
                resposta = process_backend_response(result)
                add_message("assistant", resposta)
                st.session_state.iniciado = True
                st.rerun()
    st.stop()


# ---------------------------------------------------------------------------
# Chat ativo
# ---------------------------------------------------------------------------

# Exibe histórico
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Botão de download — aparece fixo após o histórico quando há PDF
if st.session_state.pdf_data:
    st.download_button(
        label="📄 Baixar Planta de Cálculo (PDF)",
        data=st.session_state.pdf_data,
        file_name=st.session_state.pdf_filename,
        mime="application/pdf",
        type="primary"
    )

# ---------------------------------------------------------------------------
# Área de ação — varia conforme stage
# ---------------------------------------------------------------------------

stage = get_stage()

# Stage: cct
if stage == "cct":
    st.markdown("---")
    uploaded_cct = st.file_uploader("Envie a CCT em PDF", type=["pdf"], key="upload_cct")
    col1, col2 = st.columns(2)
    with col1:
        if uploaded_cct and st.button("Enviar CCT", type="primary", use_container_width=True):
            with st.spinner("Indexando CCT..."):
                pdfs_b64 = [base64.b64encode(uploaded_cct.read()).decode("utf-8")]
                result = send_message("cct enviada", pdfs_b64=pdfs_b64, tipo_pdf="cct")
                resposta = process_backend_response(result)
                add_message("assistant", resposta)
                st.rerun()
    with col2:
        if st.button("Pular CCT", use_container_width=True):
            with st.spinner("..."):
                result = send_message("pular")
                resposta = process_backend_response(result)
                add_message("assistant", resposta)
                st.rerun()

# Stage: payslip
elif stage == "payslip":
    st.markdown("---")
    uploaded_holerites = st.file_uploader(
        "Envie os holerites em PDF (pode selecionar mais de um)",
        type=["pdf"],
        accept_multiple_files=True,
        key="upload_holerites"
    )
    if uploaded_holerites and st.button("Enviar holerites", type="primary", use_container_width=True):
        with st.spinner("Processando holerites..."):
            pdfs_b64 = files_to_b64(uploaded_holerites)
            result = send_message("holerites enviados", pdfs_b64=pdfs_b64, tipo_pdf="holerite")
            resposta = process_backend_response(result)
            add_message("assistant", resposta)
            st.rerun()

# Stage: review_inputs
elif stage == "review_inputs":
    st.markdown("---")
    uploaded_cct_late = st.file_uploader("Enviar CCT agora (opcional)", type=["pdf"], key="upload_cct_late")
    col1, col2 = st.columns(2)
    with col1:
        if uploaded_cct_late and st.button("Enviar CCT", type="secondary", use_container_width=True):
            with st.spinner("Indexando CCT..."):
                pdfs_b64 = [base64.b64encode(uploaded_cct_late.read()).decode("utf-8")]
                result = send_message("cct enviada", pdfs_b64=pdfs_b64, tipo_pdf="cct")
                resposta = process_backend_response(result)
                add_message("assistant", resposta)
                st.rerun()
    with col2:
        if st.button("Continuar →", type="primary", use_container_width=True):
            with st.spinner("Analisando folha..."):
                result = send_message("continuar")
                resposta = process_backend_response(result)
                add_message("assistant", resposta)
                st.rerun()

# Stage: interviewing
elif stage == "interviewing":
    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("⚡ Pular", use_container_width=True, help="Gera a planta com pendências marcadas como risco"):
            with st.spinner("Gerando planta..."):
                result = send_message("pular")
                resposta = process_backend_response(result)
                add_message("assistant", resposta)
            with st.chat_message("assistant"):
                st.markdown(resposta)
            st.rerun()
    if prompt := st.chat_input("Responda sobre as rubricas..."):
        add_message("user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Processando..."):
                result = send_message(prompt)
                resposta = process_backend_response(result)
            st.markdown(resposta)
            add_message("assistant", resposta)
        # Rerun só se stage mudou
        novo_stage = get_stage()
        if novo_stage != "interviewing":
            st.rerun()

# Stage: ready
elif stage == "ready":
    st.markdown("---")
    if st.button("🗺️ Gerar blueprint", type="primary", use_container_width=True):
        with st.spinner("Gerando planta de cálculo..."):
            result = send_message("gerar")
            resposta = process_backend_response(result)
            add_message("assistant", resposta)
        with st.chat_message("assistant"):
            st.markdown(resposta)
        if st.session_state.pdf_data:
            st.download_button(
                label="📄 Baixar Planta de Cálculo (PDF)",
                data=st.session_state.pdf_data,
                file_name=st.session_state.pdf_filename,
                mime="application/pdf",
                type="primary"
            )

# Stage: done — conversa encerrada, sem input
elif stage == "done":
    pass

# Fallback — identification e outros
else:
    if prompt := st.chat_input("Digite sua mensagem..."):
        add_message("user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Processando..."):
                result = send_message(prompt)
                resposta = process_backend_response(result)
            st.markdown(resposta)
            add_message("assistant", resposta)
        novo_stage = get_stage()
        if novo_stage != stage:
            st.rerun()

scroll_to_bottom()