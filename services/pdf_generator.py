import io
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors


def generate_blueprint_pdf(discovery: dict, order_data: dict = None) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    title_style = ParagraphStyle("title", fontSize=14, fontName="Helvetica-Bold", spaceAfter=2)
    section_style = ParagraphStyle("section", fontSize=10, fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=14)
    small_style = ParagraphStyle("small", fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#666666"), spaceAfter=2)
    normal = ParagraphStyle("normal", fontSize=9, fontName="Helvetica", spaceAfter=3, leading=13)
    alert_style = ParagraphStyle("alert", fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#993C1D"), spaceAfter=3)
    cell_style = ParagraphStyle("cell", fontSize=8, fontName="Helvetica", leading=11)
    header_style = ParagraphStyle("header", fontSize=8, fontName="Helvetica-Bold", leading=11)
    green_style = ParagraphStyle("green", fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#2D6A2D"), leading=11)
    red_style = ParagraphStyle("red", fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#8B1A1A"), leading=11)

    elements = []

    rubricas = discovery.get("rubricas", [])
    company = discovery.get("company", "")
    proventos = [r for r in rubricas if r.get("tipo") == "provento"]
    descontos = [r for r in rubricas if r.get("tipo") == "desconto"]
    total = len(rubricas)
    alta = len([r for r in rubricas if r.get("confianca") == "alta"])
    media = len([r for r in rubricas if r.get("confianca") == "media"])
    baixa = len([r for r in rubricas if r.get("confianca") == "baixa"])

    # Header
    elements.append(Paragraph(f"Planta de Cálculo — {company}", title_style))
    elements.append(Paragraph("Gerado pelo Discovery Agent", small_style))
    elements.append(Spacer(1, 0.3*cm))

    # Sumário executivo
    elements.append(Paragraph("Sumário Executivo", section_style))
    summary_data = [
        ["Total de rubricas", str(total)],
        ["Classificadas com alta confiança", str(alta)],
        ["Requerem revisão", str(media)],
        ["Requerem decisão humana", str(baixa)],
        ["Proventos", str(len(proventos))],
        ["Descontos", str(len(descontos))],
    ]
    summary_table = Table(summary_data, colWidths=[10*cm, 3*cm])
    summary_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(summary_table)

    # Alertas
    alertas = [r for r in rubricas if r.get("observacao") and r.get("confianca") in ("media", "baixa")]
    if alertas:
        elements.append(Paragraph("Alertas e Riscos", section_style))
        for r in alertas:
            elements.append(Paragraph(f"! {r.get('nome')}: {r.get('observacao', '')}", alert_style))

    # Proventos
    elements.append(Paragraph("Proventos", section_style))
    prov_data = [[
        Paragraph("Rubrica", header_style),
        Paragraph("Natureza", header_style),
        Paragraph("Fórmula", header_style),
        Paragraph("INSS", header_style),
        Paragraph("IRRF", header_style),
        Paragraph("FGTS", header_style),
        Paragraph("Férias", header_style),
        Paragraph("13º", header_style),
        Paragraph("Certeza", header_style)
    ]]
    for r in proventos:
        prov_data.append([
            Paragraph(r.get("nome", ""), cell_style),
            Paragraph(r.get("natureza", ""), cell_style),
            Paragraph(r.get("formula", ""), cell_style),
            Paragraph("S", green_style) if r.get("incide_inss") else Paragraph("N", red_style),
            Paragraph("S", green_style) if r.get("incide_irrf") else Paragraph("N", red_style),
            Paragraph("S", green_style) if r.get("incide_fgts") else Paragraph("N", red_style),
            Paragraph("S", green_style) if r.get("reflexo_ferias") else Paragraph("N", red_style),
            Paragraph("S", green_style) if r.get("reflexo_13") else Paragraph("N", red_style),
            Paragraph(_certeza_text(r.get("confianca", "")), cell_style)
        ])

    prov_table = Table(prov_data, colWidths=[4*cm, 2.5*cm, 10.6*cm, 1*cm, 1*cm, 1*cm, 1.3*cm, 0.9*cm, 1.9*cm])
    prov_table.setStyle(_table_style())
    elements.append(prov_table)

    # Descontos
    elements.append(Paragraph("Descontos", section_style))
    desc_data = [[
        Paragraph("Rubrica", header_style),
        Paragraph("Natureza", header_style),
        Paragraph("Fórmula", header_style),
        Paragraph("Certeza", header_style)
    ]]
    for r in descontos:
        desc_data.append([
            Paragraph(r.get("nome", ""), cell_style),
            Paragraph(r.get("natureza", ""), cell_style),
            Paragraph(r.get("formula", ""), cell_style),
            Paragraph(_certeza_text(r.get("confianca", "")), cell_style)
        ])

    desc_table = Table(desc_data, colWidths=[3.5*cm, 3*cm, 17*cm, 2.2*cm])
    desc_table.setStyle(_table_style())
    elements.append(desc_table)

    # Dependências
    if order_data:
        dep_map = _build_dep_map(rubricas, order_data)
        elements.append(Paragraph("Dependências", section_style))

        dep_data = [[
            Paragraph("Rubrica", header_style),
            Paragraph("Depende de", header_style),
            Paragraph("Dispara", header_style)
        ]]
        for r in rubricas:
            nome = r.get("nome", "")
            deps = dep_map.get(nome, {})
            dep_data.append([
                Paragraph(nome, cell_style),
                Paragraph(", ".join(deps.get("depende_de", [])) or "—", cell_style),
                Paragraph(", ".join(deps.get("dispara", [])) or "—", cell_style)
            ])

        dep_table = Table(dep_data, colWidths=[5*cm, 9*cm, 9*cm])
        dep_table.setStyle(_table_style())
        elements.append(dep_table)

    # Ordem de cálculo
    if order_data:
        elements.append(Paragraph("Ordem de Cálculo", section_style))
        for step in order_data.get("ordem", []):
            deps = step.get("depende_de", [])
            dep_text = f" <- {', '.join(deps)}" if deps else ""
            elements.append(Paragraph(f"{step['passo']}. {step['rubrica']}{dep_text}", normal))
            elements.append(Paragraph(step.get("observacao", ""), small_style))

        bases = order_data.get("bases", {})
        if bases:
            elements.append(Spacer(1, 0.3*cm))
            elements.append(Paragraph("Bases de Cálculo", section_style))
            elements.append(Paragraph(f"Base INSS: {', '.join(bases.get('base_inss', []))}", normal))
            elements.append(Paragraph(f"Base IRRF: {', '.join(bases.get('base_irrf', []))}", normal))
            elements.append(Paragraph(f"Base FGTS: {', '.join(bases.get('base_fgts', []))}", normal))

        formula = order_data.get("formula_liquido", "")
        if formula:
            elements.append(Spacer(1, 0.2*cm))
            elements.append(Paragraph("Formula do Liquido", section_style))
            elements.append(Paragraph(formula, normal))

    # Base legal
    elements.append(Paragraph("Base Legal por Rubrica", section_style))
    for r in rubricas:
        base = r.get("base_legal", "")
        obs = r.get("observacao", "")
        if base:
            elements.append(Paragraph(f"{r.get('nome')}: {base}", normal))
        if obs:
            elements.append(Paragraph(obs, small_style))
        elements.append(Spacer(1, 0.1*cm))

    # Legenda
    elements.append(Spacer(1, 0.4*cm))
    elements.append(Paragraph("OK = classificacao confirmada  |  Revisar = revisar antes de migrar  |  Decidir = requer decisao humana", small_style))
    elements.append(Paragraph("S = incide (verde)  |  N = nao incide (vermelho)", small_style))

    doc.build(elements)
    return buffer.getvalue()


def _certeza_text(confianca: str) -> str:
    return {"alta": "OK", "media": "Revisar", "baixa": "Decidir"}.get(confianca, "?")


def _table_style():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ])


def _build_dep_map(rubricas: list, order_data: dict) -> dict:
    rubrica_names = {r.get("nome") for r in rubricas}
    dep_map = {name: {"depende_de": [], "dispara": []} for name in rubrica_names}

    for step in order_data.get("ordem", []):
        name = step.get("rubrica", "")
        if name not in rubrica_names:
            continue
        deps = [d for d in step.get("depende_de", []) if d in rubrica_names]
        dep_map[name]["depende_de"] = deps
        for dep in deps:
            if dep in dep_map:
                dep_map[dep]["dispara"].append(name)

    return dep_map