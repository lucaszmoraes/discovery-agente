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
    normal = styles["Normal"]
    
    title_style = ParagraphStyle("title", fontSize=14, fontName="Helvetica-Bold", spaceAfter=4)
    section_style = ParagraphStyle("section", fontSize=11, fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=14)
    small_style = ParagraphStyle("small", fontSize=9, fontName="Helvetica", textColor=colors.grey)

    elements = []

    # Header
    elements.append(Paragraph(f"Planta de Cálculo — {discovery.get('company', '')}", title_style))
    elements.append(Paragraph(f"Gerado pelo Discovery Agent", small_style))
    elements.append(Spacer(1, 0.4*cm))

    rubricas = discovery.get("rubricas", [])
    proventos = [r for r in rubricas if r.get("tipo") == "provento"]
    descontos = [r for r in rubricas if r.get("tipo") == "desconto"]

    certeza_map = {"alta": "✅", "media": "⚠️", "baixa": "❌"}

    # Proventos
    elements.append(Paragraph("Proventos", section_style))

    prov_data = [["Rubrica", "Natureza", "INSS", "IRRF", "FGTS", "Férias", "13º", "Certeza"]]
    for r in proventos:
        prov_data.append([
            r.get("nome", ""),
            r.get("natureza", ""),
            "✓" if r.get("incide_inss") else "✗",
            "✓" if r.get("incide_irrf") else "✗",
            "✓" if r.get("incide_fgts") else "✗",
            "✓" if r.get("reflexo_ferias") else "✗",
            "✓" if r.get("reflexo_13") else "✗",
            certeza_map.get(r.get("confianca", ""), "?")
        ])

    prov_table = Table(prov_data, colWidths=[3.8*cm, 2.8*cm, 1.1*cm, 1.1*cm, 1.1*cm, 1.1*cm, 1.1*cm, 1.5*cm])
    prov_table.setStyle(_table_style())
    elements.append(prov_table)

    # Descontos
    elements.append(Paragraph("Descontos", section_style))

    desc_data = [["Rubrica", "Natureza", "Certeza"]]
    for r in descontos:
        desc_data.append([
            r.get("nome", ""),
            r.get("natureza", ""),
            certeza_map.get(r.get("confianca", ""), "?")
        ])

    desc_table = Table(desc_data, colWidths=[5*cm, 5*cm, 2*cm])
    desc_table.setStyle(_table_style())
    elements.append(desc_table)

    # Ordem de cálculo
    if order_data:
        elements.append(Paragraph("Ordem de Cálculo", section_style))

        for step in order_data.get("ordem", []):
            deps = step.get("depende_de", [])
            dep_text = f" ← {', '.join(deps)}" if deps else ""
            elements.append(Paragraph(
                f"{step['passo']}. {step['rubrica']}{dep_text}",
                normal
            ))
            elements.append(Paragraph(step.get("observacao", ""), small_style))
            elements.append(Spacer(1, 0.1*cm))

        bases = order_data.get("bases", {})
        if bases:
            elements.append(Spacer(1, 0.3*cm))
            elements.append(Paragraph("Bases de Cálculo", section_style))
            elements.append(Paragraph(f"Base INSS: {', '.join(bases.get('base_inss', []))}", normal))
            elements.append(Paragraph(f"Base IRRF: {', '.join(bases.get('base_irrf', []))}", normal))
            elements.append(Paragraph(f"Base FGTS: {', '.join(bases.get('base_fgts', []))}", normal))

        formula = order_data.get("formula_liquido", "")
        if formula:
            elements.append(Spacer(1, 0.3*cm))
            elements.append(Paragraph("Fórmula do Líquido", section_style))
            elements.append(Paragraph(formula, normal))

    # Base legal
    elements.append(Paragraph("Base Legal por Rubrica", section_style))
    for r in rubricas:
        base = r.get("base_legal", "")
        obs = r.get("observacao", "")
        if base:
            elements.append(Paragraph(f"<b>{r.get('nome')}</b>: {base}", normal))
        if obs:
            elements.append(Paragraph(obs, small_style))
        elements.append(Spacer(1, 0.1*cm))

    # Legenda
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph("✅ classificação confirmada  |  ⚠️ revisar antes de migrar  |  ❌ requer decisão humana", small_style))

    doc.build(elements)
    return buffer.getvalue()


def _table_style():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F5F5")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ])