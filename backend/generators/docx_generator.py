"""
Générateur de fichiers DOCX pour les résumés.

Produit un document Word bien formaté contenant :
1. Le logo Mini Fiche centré en haut
2. Un sommaire élégant sous forme de tableau Word cliquable
3. Le résumé structuré avec les styles Heading natifs de Word
"""

import os
from docx import Document
from docx.shared import Pt, Inches, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from backend.parsers.base_parser import Section


# Chemin vers le logo
LOGO_PATH = os.path.join(os.path.dirname(__file__), '..', 'assets', 'logo.png')


def generate_summary_docx(
    title: str,
    sections: list[Section],
    output_path: str
) -> str:
    """
    Génère un fichier DOCX contenant le logo, le sommaire cliquable
    et le résumé structuré.
    """
    global _bookmark_counter
    _bookmark_counter = 0

    doc = Document()

    bookmark_names = [f"_section_{i}" for i in range(len(sections))]

    _setup_styles(doc)

    # Logo centré en haut du document
    _add_logo(doc)

    # Titre principal
    _add_title(doc, title)

    # Sommaire sous forme de tableau Word
    _add_table_of_contents(doc, sections, bookmark_names)

    # Saut de page après le sommaire
    doc.add_page_break()

    # Contenu résumé
    _add_summary_content(doc, sections, bookmark_names)

    doc.save(output_path)
    return output_path


# =========================================================================
# Palette de couleurs
# =========================================================================

BRAND_BLUE = RGBColor(0x1A, 0x3C, 0xC7)      # Bleu du logo
BRAND_BLUE_HEX = '1A3CC7'

HEADING_COLORS = {
    1: RGBColor(0x1A, 0x3C, 0xC7),  # Bleu brand
    2: RGBColor(0x2B, 0x57, 0xD4),  # Bleu moyen
    3: RGBColor(0x4A, 0x7A, 0xFF),  # Bleu clair
    4: RGBColor(0x6C, 0x6C, 0x80),  # Gris bleuté
}

HEADING_BG_COLORS = {
    1: 'E8EDF8',  # Bleu très pâle
    2: 'EEF2FB',  # Bleu ultra pâle
    3: 'F5F7FD',  # Bleu quasi-blanc
    4: 'F8F8FA',  # Gris très pâle
}


# =========================================================================
# Compteur de bookmarks
# =========================================================================

_bookmark_counter = 0


def _add_bookmark(paragraph, bookmark_name: str):
    """Ajoute un bookmark (ancre) sur un paragraphe pour les liens internes."""
    global _bookmark_counter
    _bookmark_counter += 1
    bm_id = str(_bookmark_counter)

    bookmark_start = OxmlElement('w:bookmarkStart')
    bookmark_start.set(qn('w:id'), bm_id)
    bookmark_start.set(qn('w:name'), bookmark_name)
    paragraph._p.insert(0, bookmark_start)

    bookmark_end = OxmlElement('w:bookmarkEnd')
    bookmark_end.set(qn('w:id'), bm_id)
    paragraph._p.append(bookmark_end)


def _add_internal_hyperlink(paragraph, text: str, anchor: str,
                            font_size, color: RGBColor, bold: bool = False):
    """Crée un hyperlien interne (vers un bookmark) dans un paragraphe."""
    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('w:anchor'), anchor)

    run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')

    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Calibri')
    rFonts.set(qn('w:hAnsi'), 'Calibri')
    rPr.append(rFonts)

    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), str(int(font_size * 2)))
    rPr.append(sz)

    c = OxmlElement('w:color')
    c.set(qn('w:val'), str(color))
    rPr.append(c)

    if bold:
        b = OxmlElement('w:b')
        rPr.append(b)

    u = OxmlElement('w:u')
    u.set(qn('w:val'), 'none')
    rPr.append(u)

    run.append(rPr)
    t = OxmlElement('w:t')
    t.set(qn('xml:space'), 'preserve')
    t.text = text
    run.append(t)

    hyperlink.append(run)
    paragraph._p.append(hyperlink)


# =========================================================================
# Helpers XML
# =========================================================================

def _add_paragraph_shading(paragraph, color_hex: str):
    """Ajoute un fond coloré à un paragraphe."""
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), color_hex)
    pPr.append(shd)


def _add_bottom_border(paragraph, color_hex: str, size: str = '6'):
    """Ajoute une bordure inférieure colorée à un paragraphe."""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), size)
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), color_hex)
    pBdr.append(bottom)
    pPr.append(pBdr)


# =========================================================================
# Styles
# =========================================================================

def _setup_styles(doc: Document):
    """Configure les styles de base du document."""
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)
    font.color.rgb = RGBColor(0x2C, 0x2C, 0x2C)

    paragraph_format = style.paragraph_format
    paragraph_format.space_after = Pt(6)
    paragraph_format.line_spacing = 1.15

    heading_configs = [
        ('Heading 1', 18, HEADING_COLORS[1]),
        ('Heading 2', 15, HEADING_COLORS[2]),
        ('Heading 3', 13, HEADING_COLORS[3]),
        ('Heading 4', 11, HEADING_COLORS[4]),
    ]

    for style_name, size, color in heading_configs:
        if style_name in doc.styles:
            heading_style = doc.styles[style_name]
            heading_style.font.name = 'Calibri'
            heading_style.font.size = Pt(size)
            heading_style.font.color.rgb = color
            heading_style.font.bold = True


# =========================================================================
# Logo
# =========================================================================

def _add_logo(doc: Document):
    """Ajoute le logo Mini Fiche centré en haut du document."""
    logo_path = os.path.normpath(LOGO_PATH)
    if not os.path.exists(logo_path):
        return

    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(8)
    run = para.add_run()
    run.add_picture(logo_path, width=Cm(4))


# =========================================================================
# Titre
# =========================================================================

def _add_title(doc: Document, title: str):
    """Ajoute le titre principal centré."""
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_para.paragraph_format.space_after = Pt(4)
    title_para.paragraph_format.space_before = Pt(4)
    run = title_para.add_run(f"Résumé — {title}")
    run.bold = True
    run.font.size = Pt(22)
    run.font.name = 'Calibri'
    run.font.color.rgb = BRAND_BLUE

    # Ligne séparatrice
    sep_para = doc.add_paragraph()
    sep_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_bottom_border(sep_para, BRAND_BLUE_HEX, '12')
    sep_para.paragraph_format.space_after = Pt(16)


# =========================================================================
# Sommaire — Style classique Word, auto-généré
# =========================================================================

def _add_table_of_contents(doc: Document, sections: list[Section],
                           bookmark_names: list[str]):
    """
    Génère automatiquement un sommaire classique Word.
    Entrées indentées par niveau, pointillés, liens cliquables.
    """
    # Titre "Table des matières"
    toc_title = doc.add_paragraph()
    toc_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    toc_title.paragraph_format.space_after = Pt(16)
    run = toc_title.add_run("Table des matières")
    run.bold = True
    run.font.size = Pt(16)
    run.font.name = 'Calibri'
    run.font.color.rgb = BRAND_BLUE
    _add_bottom_border(toc_title, BRAND_BLUE_HEX, '8')

    # Page utile A4 ≈ 16cm → 9072 twips
    PAGE_WIDTH_TWIPS = 9072
    INDENT_TWIPS = 454  # ~0.8cm par niveau

    for i, section in enumerate(sections):
        level = min(section.level, 4)

        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(2 if level == 1 else 0)
        para.paragraph_format.space_after = Pt(2 if level == 1 else 0)

        indent_twips = INDENT_TWIPS * (level - 1)
        para.paragraph_format.left_indent = Pt(indent_twips / 20)

        # Tab stop à droite avec pointillés
        tab_pos = PAGE_WIDTH_TWIPS - indent_twips
        _add_right_tab_with_dots(para, tab_pos)

        # Config par niveau
        font_size = {1: 12, 2: 11, 3: 10.5, 4: 10}.get(level, 10)
        bold = level <= 2
        color = RGBColor(0x2C, 0x2C, 0x2C) if level <= 2 else RGBColor(0x55, 0x55, 0x55)

        # Titre en lien cliquable
        _add_internal_hyperlink(
            para, section.title, bookmark_names[i],
            font_size=font_size, color=color, bold=bold,
        )

        # Tab → déclenche les pointillés jusqu'au bord droit
        _add_tab_run(para, font_size)

    doc.add_paragraph()


def _add_right_tab_with_dots(paragraph, position_twips: int):
    """Ajoute un taquet de tabulation aligné à droite avec pointillés (en twips)."""
    pPr = paragraph._p.get_or_add_pPr()
    tabs = OxmlElement('w:tabs')
    tab = OxmlElement('w:tab')
    tab.set(qn('w:val'), 'right')
    tab.set(qn('w:leader'), 'dot')
    tab.set(qn('w:pos'), str(position_twips))
    tabs.append(tab)
    pPr.append(tabs)


def _add_tab_run(paragraph, font_size: float):
    """Ajoute un run contenant un caractère tab (pour déclencher les pointillés)."""
    r = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')
    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), str(int(font_size * 2)))
    rPr.append(sz)
    r.append(rPr)
    tab = OxmlElement('w:tab')
    r.append(tab)
    paragraph._p.append(r)


# =========================================================================
# Contenu résumé
# =========================================================================

def _add_summary_content(doc: Document, sections: list[Section],
                         bookmark_names: list[str]):
    """
    Ajoute le contenu résumé au document avec les styles Heading.
    Chaque titre porte un bookmark pour le lien depuis le sommaire.
    """
    for i, section in enumerate(sections):
        level = min(section.level, 4)

        heading_para = doc.add_heading(section.title, level=level)
        _add_bookmark(heading_para, bookmark_names[i])

        bg = HEADING_BG_COLORS.get(level)
        if bg:
            _add_paragraph_shading(heading_para, bg)

        if level <= 2:
            _add_bottom_border(heading_para, str(HEADING_COLORS[level]), '4')

        if section.content:
            for paragraph_text in section.content.split('\n'):
                paragraph_text = paragraph_text.strip()
                if paragraph_text:
                    doc.add_paragraph(paragraph_text)
