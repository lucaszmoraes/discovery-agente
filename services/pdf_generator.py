import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors


def generate_blueprint_pdf(discovery: dict, order_data: dict = None) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.5*cm,
        rightMargin=2.5*cm,
        topMargin=2.5*cm,
        bottomMargin=2.5*cm
    )

    styles = getSampleStyleSheet()
    normal = ParagraphStyle("normal", fontSize=9, fontName="Helvetica", spaceAfter=3, leading=13)
    title_style = ParagraphStyle("title", fontSize=14, fontName="Helvetica-Bold", spaceAfter=2)
    section_style = ParagraphStyle("section", fontSize=10, fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=14, textColor=colors.HexColor("#222222"))
    small_style = ParagraphStyle("small", fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#666666"), spaceAfter=2)
    alert_style = ParagraphStyle("alert", fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#993C1D"), spaceAfter=3)

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
    prov_data = [["Rubrica", "Natureza", "Fórmula", "INSS", "IRRF", "FGTS", "Férias", "13º", "Certeza"]]
    for r in proventos:
        prov_data.append([
            r.get("nome", ""),
            r.get("natureza", ""),
            r.get("formula", ""),
            "S" if r.get("incide_inss") else "N",
            "S" if r.get("incide_irrf") else "N",
            "S" if r.get("incide_fgts") else "N",
            "S" if r.get("reflexo_ferias") else "N",
            "S" if r.get("reflexo_13") else "N",
            _certeza_text(r.get("confianca", ""))
        ])

    prov_table = Table(prov_data, colWidths=[2.8*cm, 2.2*cm, 4*cm, 0.9*cm, 0.9*cm, 0.9*cm, 0.9*cm, 0.9*cm, 1.3*cm])
    prov_table.setStyle(_table_style_with_colors(len(prov_data), [3, 4, 5, 6, 7]))
    elements.append(prov_table)

    # Descontos
    elements.append(Paragraph("Descontos", section_style))
    desc_data = [["Rubrica", "Natureza", "Fórmula", "Certeza"]]
    for r in descontos:
        desc_data.append([
            r.get("nome", ""),
            r.get("natureza", ""),
            r.get("formula", ""),
            _certeza_text(r.get("confianca", ""))
        ])

    desc_table = Table(desc_data, colWidths=[3*cm, 3*cm, 6.5*cm, 1.3*cm])
    desc_table.setStyle(_table_style())
    elements.append(desc_table)

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
    elements.append(Paragraph("S = incide / N = nao incide", small_style))

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


def _table_style_with_colors(num_rows: int, incidence_cols: list):
    style = _table_style()
    green = colors.HexColor("#2D6A2D")
    red = colors.HexColor("#8B1A1A")

    for row in range(1, num_rows):
        for col in incidence_cols:
            style.add("TEXTCOLOR", (col, row), (col, row), green)

    return style