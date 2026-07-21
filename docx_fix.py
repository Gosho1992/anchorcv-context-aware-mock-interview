# docx_fix.py
# ============================================================
# Two entry points:
#   build_docx_from_cv_data(cv_data)  → structured CV from CVData object (Tab 2)
#   create_docx_from_text(text)       → formatted document from plain AI text (Tab 1)
# ============================================================

from io import BytesIO
import re
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────
COLOR_PRIMARY   = RGBColor(0x1e, 0x3c, 0x72)   # dark navy  — headings / name
COLOR_ACCENT    = RGBColor(0x21, 0x96, 0xF3)   # blue       — section rule lines
COLOR_BODY      = RGBColor(0x22, 0x22, 0x22)   # near-black — body text
COLOR_MUTED     = RGBColor(0x55, 0x55, 0x55)   # grey       — dates, captions
COLOR_EVIDENCE  = RGBColor(0x85, 0x64, 0x04)   # amber      — evidence anchors
COLOR_WHITE     = RGBColor(0xFF, 0xFF, 0xFF)


# ─────────────────────────────────────────────
# LOW-LEVEL HELPERS
# ─────────────────────────────────────────────

def _set_cell_bg(cell, hex_color: str):
    """Set background fill on a table cell."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def _add_horizontal_rule(doc: Document, color: RGBColor = COLOR_ACCENT):
    """Add a thin coloured horizontal rule paragraph."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after  = Pt(4)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'),  '6')
    bottom.set(qn('w:space'), '1')
    # RGBColor stores as bytes — format via str() which gives 'RRGGBB'
    hex_color = str(color).upper()
    bottom.set(qn('w:color'), hex_color)
    pBdr.append(bottom)
    pPr.append(pBdr)
    return p


def _section_heading(doc: Document, title: str):
    """Bold navy section heading + blue underline rule."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(0)
    run = p.add_run(title.upper())
    run.bold      = True
    run.font.size = Pt(11)
    run.font.color.rgb = COLOR_PRIMARY
    _add_horizontal_rule(doc)
    return p


def _body_para(doc: Document, text: str, indent: float = 0,
               bold: bool = False, italic: bool = False,
               color: RGBColor = None, size: int = 10,
               space_after: int = 4) -> None:
    """Add a body paragraph with optional formatting."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after  = Pt(space_after)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)

    # Split on inline bold (**text**) and evidence anchors
    parts = re.split(r'(\*\*.*?\*\*|\(Evidence:.*?\))', text)
    for part in parts:
        if not part:
            continue
        run = p.add_run()
        if part.startswith('**') and part.endswith('**'):
            run.text = part[2:-2]
            run.bold = True
        elif part.startswith('(Evidence:'):
            run.text = part
            run.font.color.rgb = COLOR_EVIDENCE
            run.italic = True
            run.font.size = Pt(9)
        else:
            run.text = part
            run.bold   = bold
            run.italic = italic
        run.font.size      = Pt(size)
        run.font.color.rgb = color or COLOR_BODY
    return p


def _bullet(doc: Document, text: str, indent: float = 0.5):
    """Add a bullet point paragraph."""
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.left_indent  = Cm(indent)
    p.paragraph_format.space_after  = Pt(3)
    p.paragraph_format.space_before = Pt(0)
    # Handle inline bold + evidence anchors
    parts = re.split(r'(\*\*.*?\*\*|\(Evidence:.*?\))', text)
    for part in parts:
        if not part:
            continue
        run = p.add_run()
        if part.startswith('**') and part.endswith('**'):
            run.text = part[2:-2]
            run.bold = True
        elif part.startswith('(Evidence:'):
            run.text = part
            run.font.color.rgb = COLOR_EVIDENCE
            run.italic = True
            run.font.size = Pt(9)
        else:
            run.text = part
        run.font.size = Pt(10)
    return p


def _set_page_margins(doc: Document,
                      top=1.8, bottom=1.8, left=2.0, right=2.0):
    """Set page margins in cm."""
    for section in doc.sections:
        section.top_margin    = Cm(top)
        section.bottom_margin = Cm(bottom)
        section.left_margin   = Cm(left)
        section.right_margin  = Cm(right)


# ─────────────────────────────────────────────
# ENTRY POINT 1 — Plain AI text  (Tab 1)
# ─────────────────────────────────────────────

def create_docx_from_text(text: str) -> BytesIO:
    """
    Convert a plain-text or lightly-markdown AI response
    into a well-formatted DOCX.

    Handles:
      - # / ## / ### headings
      - - / * bullet lists
      - **inline bold**
      - (Evidence: "...") amber highlights
      - blank lines as paragraph spacing
    """
    doc = Document()
    _set_page_margins(doc)

    # Default body style
    style = doc.styles['Normal']
    style.font.name  = 'Calibri'
    style.font.size  = Pt(10)
    style.font.color.rgb = COLOR_BODY

    if not text or not text.strip():
        doc.add_paragraph("No content to export.")
        buf = BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf

    # Clean up
    text = text.replace('```markdown', '').replace('```', '').strip()
    lines = text.split('\n')

    for line in lines:
        stripped = line.rstrip()

        # H1
        if stripped.startswith('# '):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after  = Pt(2)
            run = p.add_run(stripped[2:])
            run.bold = True
            run.font.size = Pt(14)
            run.font.color.rgb = COLOR_PRIMARY
            _add_horizontal_rule(doc)

        # H2
        elif stripped.startswith('## '):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after  = Pt(2)
            run = p.add_run(stripped[3:].upper())
            run.bold = True
            run.font.size = Pt(11)
            run.font.color.rgb = COLOR_PRIMARY
            _add_horizontal_rule(doc)

        # H3
        elif stripped.startswith('### '):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after  = Pt(2)
            run = p.add_run(stripped[4:])
            run.bold = True
            run.font.size = Pt(10.5)
            run.font.color.rgb = COLOR_PRIMARY

        # Bullet
        elif stripped.startswith('- ') or stripped.startswith('* '):
            _bullet(doc, stripped[2:])

        # ALL-CAPS section title (e.g. "GOAL", "OBSTACLES", "LEVERAGE")
        elif stripped and stripped == stripped.upper() and len(stripped) > 2 and not any(c.isdigit() for c in stripped):
            _section_heading(doc, stripped)

        # Blank line
        elif not stripped:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)

        # Normal paragraph
        else:
            _body_para(doc, stripped)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def create_docx_from_html(html: str) -> BytesIO:
    """
    Convert rendered HTML into a DOCX while preserving headings and bullets.
    This keeps DOCX content aligned with the same HTML used for PDF export.
    """
    if not html or not html.strip():
        return create_docx_from_text("")

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style"]):
        tag.decompose()

    for tag in soup.find_all("br"):
        tag.replace_with("\n")

    def normalize_line(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    for tag in soup.find_all(["h1", "h2", "h3", "div"]):
        text = normalize_line(tag.get_text(" ", strip=True))
        if not text:
            continue

        style = (tag.get("style") or "").lower()
        is_name_heading = "font-size: 22" in style or "font-size: 24" in style
        is_section_heading = "text-transform: uppercase" in style and "font-weight: 900" in style

        if tag.name == "h1" or is_name_heading:
            tag.replace_with(f"\n# {text}\n")
        elif tag.name in {"h2", "h3"} or is_section_heading:
            tag.replace_with(f"\n## {text}\n")

    for tag in soup.find_all("li"):
        text = normalize_line(tag.get_text(" ", strip=True))
        tag.replace_with(f"\n- {text}\n" if text else "\n")

    text = soup.get_text("\n")
    cleaned_lines = []
    previous_blank = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue

        cleaned_lines.append(normalize_line(line))
        previous_blank = False

    cleaned_text = "\n".join(cleaned_lines).strip()
    return create_docx_from_text(cleaned_text)


# ─────────────────────────────────────────────
# ENTRY POINT 2 — Structured CVData  (Tab 2)
# ─────────────────────────────────────────────

def build_docx_from_cv_data(cv) -> BytesIO:
    """
    Build a fully-structured, styled DOCX from a CVData object.

    Layout:
      Header band (navy) — name + contact on white
      PROFESSIONAL SUMMARY
      CORE SKILLS  (two-column table)
      PROFESSIONAL EXPERIENCE
      EDUCATION
      PROJECTS
      PUBLICATIONS
      CERTIFICATIONS
      AWARDS  (if any)
      LANGUAGES
    """
    doc = Document()
    _set_page_margins(doc, top=1.5, bottom=1.5, left=1.8, right=1.8)

    # ── Default body style ──
    style = doc.styles['Normal']
    style.font.name  = 'Calibri'
    style.font.size  = Pt(10)
    style.font.color.rgb = COLOR_BODY

    # ── 1. HEADER BAND ──
    name = (cv.name or "").strip() or "Your Name"
    header_tbl = doc.add_table(rows=1, cols=1)
    header_tbl.style = 'Table Grid'
    cell = header_tbl.cell(0, 0)
    _set_cell_bg(cell, '1e3c72')

    # Name
    np = cell.paragraphs[0]
    np.alignment = WD_ALIGN_PARAGRAPH.CENTER
    np.paragraph_format.space_before = Pt(10)
    np.paragraph_format.space_after  = Pt(4)
    nr = np.add_run(name)
    nr.bold = True
    nr.font.size = Pt(22)
    nr.font.color.rgb = COLOR_WHITE

    # Contact line
    contact_parts = [x for x in [cv.email, cv.phone, cv.location, cv.linkedin] if x]
    if contact_parts:
        cp = cell.add_paragraph()
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.paragraph_format.space_before = Pt(0)
        cp.paragraph_format.space_after  = Pt(10)
        cr = cp.add_run("  |  ".join(contact_parts))
        cr.font.size = Pt(9)
        cr.font.color.rgb = RGBColor(0xCC, 0xDD, 0xFF)

    doc.add_paragraph()  # breathing room

    # ── 2. PROFESSIONAL SUMMARY ──
    if cv.summary and cv.summary.strip():
        _section_heading(doc, "Professional Summary")
        _body_para(doc, cv.summary.strip(), italic=True, color=COLOR_MUTED)

    # ── 3. CORE SKILLS ──
    skills = cv.skills or {}
    if skills:
        _section_heading(doc, "Core Skills")
        flat_cats = [(cat, ", ".join(items)) for cat, items in skills.items() if items]
        if flat_cats:
            cols = 2
            rows_needed = (len(flat_cats) + cols - 1) // cols
            tbl = doc.add_table(rows=rows_needed, cols=cols * 2)
            tbl.style = 'Table Grid'
            for i, (cat, items_str) in enumerate(flat_cats):
                row_idx = i // cols
                col_idx = (i % cols) * 2
                # Category label cell
                label_cell = tbl.cell(row_idx, col_idx)
                _set_cell_bg(label_cell, 'E8F0FE')
                lp = label_cell.paragraphs[0]
                lr = lp.add_run(cat)
                lr.bold = True
                lr.font.size = Pt(9)
                lr.font.color.rgb = COLOR_PRIMARY
                # Items cell
                items_cell = tbl.cell(row_idx, col_idx + 1)
                ip = items_cell.paragraphs[0]
                ir = ip.add_run(items_str)
                ir.font.size = Pt(9)
                ir.font.color.rgb = COLOR_BODY
            doc.add_paragraph()

    # ── 4. PROFESSIONAL EXPERIENCE ──
    experience = cv.experience or []
    if experience:
        _section_heading(doc, "Professional Experience")
        for job in experience:
            title   = job.get("title", "")
            company = job.get("company", "")
            loc     = job.get("location", "")
            start   = job.get("start_date", "")
            end     = job.get("end_date", "Present")
            bullets = job.get("bullets", [])

            # Title + date on same line (two-col table)
            row_tbl = doc.add_table(rows=1, cols=2)
            row_tbl.style = 'Table Grid'
            lc = row_tbl.cell(0, 0)
            lp = lc.paragraphs[0]
            lr = lp.add_run(f"{title}")
            lr.bold = True
            lr.font.size = Pt(10.5)
            lr.font.color.rgb = COLOR_PRIMARY

            rc = row_tbl.cell(0, 1)
            rc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            rr = rc.paragraphs[0].add_run(f"{start} – {end}")
            rr.font.size = Pt(9)
            rr.font.color.rgb = COLOR_MUTED

            # Company / location
            sub_parts = [x for x in [company, loc] if x]
            if sub_parts:
                _body_para(doc, "  ".join(sub_parts), italic=True,
                           color=COLOR_MUTED, size=9, space_after=2)

            # Bullets
            for b in bullets:
                if str(b).strip():
                    _bullet(doc, str(b).strip())

            doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # ── 5. EDUCATION ──
    education = cv.education or []
    if education:
        _section_heading(doc, "Education")
        for edu in education:
            degree  = edu.get("degree", "")
            inst    = edu.get("institution", "")
            loc     = edu.get("location", "")
            start   = edu.get("start_date", "")
            end     = edu.get("end_date", "")
            gpa     = edu.get("gpa", "")
            thesis  = edu.get("thesis", "")

            row_tbl = doc.add_table(rows=1, cols=2)
            row_tbl.style = 'Table Grid'
            lc = row_tbl.cell(0, 0)
            lr = lc.paragraphs[0].add_run(degree)
            lr.bold = True
            lr.font.size = Pt(10.5)
            lr.font.color.rgb = COLOR_PRIMARY

            rc = row_tbl.cell(0, 1)
            rc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            date_str = f"{start} – {end}" if start else end
            rr = rc.paragraphs[0].add_run(date_str)
            rr.font.size = Pt(9)
            rr.font.color.rgb = COLOR_MUTED

            sub_parts = [x for x in [inst, loc] if x]
            if sub_parts:
                _body_para(doc, "  ".join(sub_parts), italic=True,
                           color=COLOR_MUTED, size=9, space_after=2)
            if gpa:
                _body_para(doc, f"GPA: {gpa}", color=COLOR_MUTED, size=9)
            if thesis:
                _body_para(doc, f"Thesis: {thesis}", italic=True,
                           color=COLOR_MUTED, size=9)
            doc.add_paragraph().paragraph_format.space_after = Pt(3)

    # ── 6. PROJECTS ──
    projects = cv.projects or []
    if projects:
        _section_heading(doc, "Projects")
        for proj in projects:
            pname = proj.get("name", "")
            pdesc = proj.get("description", "")
            pbullets = proj.get("bullets", [])
            if pname:
                _body_para(doc, pname, bold=True,
                           color=COLOR_PRIMARY, size=10.5)
            if pdesc:
                _body_para(doc, pdesc, italic=True,
                           color=COLOR_MUTED, size=9)
            for b in pbullets:
                if str(b).strip():
                    _bullet(doc, str(b).strip())
            doc.add_paragraph().paragraph_format.space_after = Pt(3)

    # ── 7. PUBLICATIONS ──
    publications = cv.publications or []
    if publications:
        _section_heading(doc, "Publications")
        for pub in publications:
            if str(pub).strip():
                _bullet(doc, str(pub).strip())

    # ── 8. CERTIFICATIONS ──
    certifications = cv.certifications or []
    if certifications:
        _section_heading(doc, "Certifications")
        for cert in certifications:
            cname   = cert.get("name", "")
            cissuer = cert.get("issuer", "")
            cyear   = cert.get("year", "")
            parts   = [x for x in [cname, cissuer, cyear] if x]
            if parts:
                _bullet(doc, "  —  ".join(parts))

    # ── 9. AWARDS ──
    awards = cv.awards or []
    if awards:
        _section_heading(doc, "Awards & Honours")
        for award in awards:
            if str(award).strip():
                _bullet(doc, str(award).strip())

    # ── 10. LANGUAGES ──
    languages = cv.languages or []
    if languages:
        _section_heading(doc, "Languages")
        lang_parts = []
        for lang in languages:
            lname = lang.get("language", "")
            lprof = lang.get("proficiency", "")
            if lname:
                lang_parts.append(f"{lname} ({lprof})" if lprof else lname)
        if lang_parts:
            _body_para(doc, "  |  ".join(lang_parts))

    # ── SAVE ──
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
