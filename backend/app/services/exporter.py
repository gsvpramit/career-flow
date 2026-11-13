"""Clean single-column Big Tech ATS resume exporter (.pdf via ReportLab, .docx via python-docx)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Sequence

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.app.schemas.job import ATSReport, JobAnalysis
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.timezone_utils import eastern_today_str


def _slugify(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return cleaned[:40] or fallback


def build_output_folder_name(company: str, title: str, job_id: int) -> str:
    """Create deterministic organized folder name under output/."""
    date_prefix = eastern_today_str()
    return f"{date_prefix}_{_slugify(company, 'company')}_{_slugify(title, 'role')}_j{job_id}"


def _build_contact_line(resume: CanonicalResume) -> str:
    c = resume.contact
    parts = [p.strip() for p in (c.location, c.phone, c.email, c.linkedin, c.github, c.portfolio) if p and p.strip()]
    return "  |  ".join(parts)


def render_pdf_resume(resume: CanonicalResume, output_path: Path, page_budget: float = 1.5) -> bool:
    """Render single-column Big Tech PDF via ReportLab and verify selectable text layer."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    compact = float(page_budget or 1.5) <= 1.05
    expanded = float(page_budget or 1.5) >= 2.5
    margin = (0.38 if compact else (0.52 if expanded else 0.46)) * inch
    usable_width = letter[0] - 2 * margin
    body_size = 8.4 if compact else (9.3 if expanded else 8.9)
    leading_sz = 10.4 if compact else (11.8 if expanded else 11.2)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=(0.35 if compact else (0.50 if expanded else 0.42)) * inch,
        bottomMargin=(0.35 if compact else (0.50 if expanded else 0.42)) * inch,
        title=f"{resume.contact.full_name} Resume",
    )

    name_style = ParagraphStyle(
        "NameHeader",
        fontName="Helvetica-Bold",
        fontSize=14.5 if compact else 15.5,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    contact_style = ParagraphStyle(
        "ContactLine",
        fontName="Helvetica",
        fontSize=8.5 if compact else 8.8,
        leading=11,
        alignment=TA_CENTER,
        spaceAfter=5,
    )
    section_style = ParagraphStyle(
        "SectionHeader",
        fontName="Helvetica-Bold",
        fontSize=9.2 if compact else (10.5 if expanded else 9.8),
        leading=12,
        spaceBefore=3.5 if compact else (7 if expanded else 5),
        spaceAfter=2,
        textColor=colors.black,
    )
    item_left_style = ParagraphStyle(
        "ItemLeft",
        fontName="Helvetica-Bold",
        fontSize=9.2 if compact else 9.5,
        leading=11.5,
        alignment=TA_LEFT,
    )
    item_right_style = ParagraphStyle(
        "ItemRight",
        fontName="Helvetica",
        fontSize=body_size,
        leading=11.5,
        alignment=TA_RIGHT,
    )
    sub_left_style = ParagraphStyle(
        "SubLeft",
        fontName="Helvetica-Oblique",
        fontSize=body_size,
        leading=11,
        alignment=TA_LEFT,
    )
    bullet_style = ParagraphStyle(
        "BulletItem",
        fontName="Helvetica",
        fontSize=body_size,
        leading=leading_sz,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=0.8 if compact else (2.2 if expanded else 1.5),
    )
    body_style = ParagraphStyle(
        "BodyLine",
        fontName="Helvetica",
        fontSize=body_size,
        leading=leading_sz,
        spaceAfter=2,
    )

    story: list[object] = [Paragraph(escape(resume.contact.full_name), name_style)]
    contact_line = _build_contact_line(resume)
    if contact_line:
        story.append(Paragraph(escape(contact_line), contact_style))

    def add_section_heading(title: str) -> None:
        story.append(Paragraph(escape(title.upper()), section_style))
        story.append(HRFlowable(width="100%", thickness=0.7, color=colors.black, spaceAfter=4))

    def add_split_row(left_html: str, right_text: str, left_sty: ParagraphStyle, right_sty: ParagraphStyle) -> None:
        tbl = Table(
            [[Paragraph(left_html, left_sty), Paragraph(escape(right_text), right_sty)]],
            colWidths=[usable_width * 0.72, usable_width * 0.28],
        )
        tbl.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(tbl)

    if resume.summary:
        add_section_heading("Summary")
        story.append(Paragraph(escape(resume.summary), body_style))

    if resume.experience:
        add_section_heading("Experience")
        for exp in resume.experience:
            date_span = f"{exp.start_date} - {exp.end_date}".strip(" -")
            role_tags: list[str] = []
            for b in exp.bullets:
                for t in (b.tags or []):
                    if t and t not in role_tags:
                        role_tags.append(t)
            tech_suffix = f" &mdash; <font color='#4a5568'>{', '.join(role_tags[:4])}</font>" if role_tags else ""
            add_split_row(f"<b>{escape(exp.title)}</b>{tech_suffix}", date_span, item_left_style, item_right_style)
            add_split_row(escape(exp.company), exp.location, sub_left_style, item_right_style)
            for bullet in exp.bullets:
                if bullet.approved:
                    story.append(Paragraph(f"&bull; {escape(bullet.text)}", bullet_style))
            story.append(Spacer(1, 3))

    if resume.projects:
        add_section_heading("Projects")
        for proj in resume.projects:
            stack = f" | {', '.join(proj.tech_stack)}" if proj.tech_stack else ""
            add_split_row(f"<b>{escape(proj.name)}</b>{escape(stack)}", "", body_style, item_right_style)
            for bullet in proj.bullets:
                if bullet.approved:
                    story.append(Paragraph(f"&bull; {escape(bullet.text)}", bullet_style))
            story.append(Spacer(1, 2))

    if resume.skills:
        add_section_heading("Technical Skills")
        for cat in resume.skills:
            if cat.items:
                story.append(
                    Paragraph(
                        f"<b>{escape(cat.category)}:</b> {escape(', '.join(cat.items))}",
                        body_style,
                    )
                )

    if resume.education:
        add_section_heading("Education")
        for edu in resume.education:
            add_split_row(escape(edu.institution), edu.location, item_left_style, item_right_style)
            degree_line = edu.degree + (f" (GPA: {edu.gpa})" if edu.gpa else "")
            add_split_row(escape(degree_line), edu.graduation_date, sub_left_style, item_right_style)
            if edu.coursework:
                story.append(
                    Paragraph(
                        f"<b>Coursework:</b> {escape(', '.join(edu.coursework))}",
                        body_style,
                    )
                )

    if resume.certifications:
        add_section_heading("Certifications")
        for cert in resume.certifications:
            issuer_part = f" — {cert.issuer}" if cert.issuer else ""
            add_split_row(
                f"<b>{escape(cert.name)}</b>{escape(issuer_part)}",
                cert.date,
                body_style,
                item_right_style,
            )

    doc.build(story)
    return verify_pdf_text_layer(output_path, resume.contact.full_name)


def verify_pdf_text_layer(pdf_path: Path, expected_name: str) -> bool:
    """Confirm the generated PDF contains selectable text with the candidate's name."""
    reader = PdfReader(str(pdf_path))
    extracted = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not extracted.strip():
        return False
    first_token = expected_name.strip().split()[0].lower() if expected_name.strip() else ""
    return (first_token in extracted.lower()) if first_token else True


def _add_bottom_border(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), "000000")
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def render_docx_resume(resume: CanonicalResume, output_path: Path, page_budget: float = 1.5) -> None:
    """Render single-column ATS-safe .docx resume using pure paragraphs (zero tables)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    compact = float(page_budget or 1.5) <= 1.05
    margin_in = 0.42 if compact else 0.5
    top_bot_in = 0.38 if compact else 0.45

    for section in doc.sections:
        section.top_margin = Inches(top_bot_in)
        section.bottom_margin = Inches(top_bot_in)
        section.left_margin = Inches(margin_in)
        section.right_margin = Inches(margin_in)

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Calibri"
    normal_style.font.size = Pt(10)
    normal_style.font.color.rgb = RGBColor(0x11, 0x11, 0x11)

    # Candidate name
    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_p.paragraph_format.space_before = Pt(0)
    name_p.paragraph_format.space_after = Pt(2)
    name_run = name_p.add_run(resume.contact.full_name)
    name_run.bold = True
    name_run.font.size = Pt(16)

    contact_line = _build_contact_line(resume)
    if contact_line:
        c_p = doc.add_paragraph()
        c_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        c_p.paragraph_format.space_before = Pt(0)
        c_p.paragraph_format.space_after = Pt(6)
        c_run = c_p.add_run(contact_line)
        c_run.font.size = Pt(9)

    def add_section_header(title: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(title.upper())
        r.bold = True
        r.font.size = Pt(10.5)
        _add_bottom_border(p)

    def add_tabbed_line(left: str, right: str, bold: bool = False, italic: bool = False) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.tab_stops.add_tab_stop(Inches(7.5), WD_TAB_ALIGNMENT.RIGHT)
        r1 = p.add_run(left)
        r1.bold = bold
        r1.italic = italic
        r1.font.size = Pt(10)
        if right:
            r2 = p.add_run(f"\t{right}")
            r2.font.size = Pt(9.5)

    def add_bullet(text: str) -> None:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(1.5)
        r = p.add_run(text)
        r.font.size = Pt(9.5)

    if resume.summary:
        add_section_header("Summary")
        p = doc.add_paragraph(resume.summary)
        p.paragraph_format.space_after = Pt(3)

    if resume.experience:
        add_section_header("Experience")
        for exp in resume.experience:
            date_span = f"{exp.start_date} - {exp.end_date}".strip(" -")
            role_tags = []
            for b in exp.bullets:
                for t in (b.tags or []):
                    if t and t not in role_tags:
                        role_tags.append(t)
            tech_suffix = f" — {', '.join(role_tags[:4])}" if role_tags else ""
            add_tabbed_line(f"{exp.title}{tech_suffix}", date_span, bold=True)
            add_tabbed_line(exp.company, exp.location, italic=True)
            for bullet in exp.bullets:
                if bullet.approved:
                    add_bullet(bullet.text)

    if resume.projects:
        add_section_header("Projects")
        for proj in resume.projects:
            stack = f" | {', '.join(proj.tech_stack)}" if proj.tech_stack else ""
            add_tabbed_line(f"{proj.name}{stack}", "", bold=True)
            for bullet in proj.bullets:
                if bullet.approved:
                    add_bullet(bullet.text)

    if resume.skills:
        add_section_header("Technical Skills")
        for cat in resume.skills:
            if not cat.items:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1.5)
            cat_r = p.add_run(f"{cat.category}: ")
            cat_r.bold = True
            cat_r.font.size = Pt(9.5)
            val_r = p.add_run(", ".join(cat.items))
            val_r.font.size = Pt(9.5)

    if resume.education:
        add_section_header("Education")
        for edu in resume.education:
            add_tabbed_line(edu.institution, edu.location, bold=True)
            degree_line = edu.degree + (f" (GPA: {edu.gpa})" if edu.gpa else "")
            add_tabbed_line(degree_line, edu.graduation_date, italic=True)
            if edu.coursework:
                cp = doc.add_paragraph()
                cp.paragraph_format.space_before = Pt(0)
                cp.paragraph_format.space_after = Pt(2)
                cr1 = cp.add_run("Coursework: ")
                cr1.bold = True
                cr1.font.size = Pt(9.0)
                cr2 = cp.add_run(", ".join(edu.coursework))
                cr2.font.size = Pt(9.0)

    if resume.certifications:
        add_section_header("Certifications")
        for cert in resume.certifications:
            issuer_part = f" — {cert.issuer}" if cert.issuer else ""
            add_tabbed_line(f"{cert.name}{issuer_part}", cert.date)

    doc.save(str(output_path))


def _clean_token(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_")
    return cleaned[:48] or fallback


def build_resume_filename_stem(
    resume: CanonicalResume,
    job: JobAnalysis,
    filename_format: str = "{full_name}_{company}_{role}",
    job_id: int | None = None,
    run_id: int | None = None,
) -> str:
    """Format a clean, unique export filename stem such as Alex_Rivera_Stripe_Senior_Engineer_J42_R7."""
    tokens = {
        "full_name": _clean_token(resume.contact.full_name or "Candidate", "Candidate"),
        "company": _clean_token(job.company or "Company", "Company"),
        "role": _clean_token(job.title or "Role", "Role"),
        "location": _clean_token(job.location or "Location", "Location"),
        "job_id": f"J{job_id}" if job_id else "",
        "run_id": f"R{run_id}" if run_id else "",
    }
    raw_fmt = (filename_format or "{full_name}_{company}_{role}").strip()
    try:
        rendered = raw_fmt.format(**tokens)
    except Exception:
        rendered = f"{tokens['full_name']}_{tokens['company']}_{tokens['role']}"

    if job_id and "{job_id}" not in raw_fmt:
        rendered = f"{rendered}_J{job_id}"
    if run_id and "{run_id}" not in raw_fmt:
        rendered = f"{rendered}_R{run_id}"

    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", rendered)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_.-")
    return sanitized[:115] or "resume"


def export_run_artifacts(
    output_root: Path,
    resume: CanonicalResume,
    job: JobAnalysis,
    report: ATSReport,
    formats: Sequence[str],
    filename_format: str = "{full_name}_{company}_{role}",
    page_budget: float = 1.5,
    run_id: int | None = None,
) -> tuple[Path, list[str], bool | None]:
    """Write resume files + JSON audit snapshots into an organized output/ subfolder."""
    folder_name = build_output_folder_name(job.company, job.title, report.job_id)
    target_dir = output_root / folder_name
    suffix = 1
    while target_dir.exists():
        suffix += 1
        target_dir = output_root / f"{folder_name}_{suffix}"
    target_dir.mkdir(parents=True, exist_ok=True)

    stem = build_resume_filename_stem(
        resume,
        job,
        filename_format,
        job_id=report.job_id or None,
        run_id=run_id,
    )
    generated: list[str] = []
    pdf_verified: bool | None = None

    if "pdf" in formats:
        pdf_name = f"{stem}.pdf"
        pdf_path = target_dir / pdf_name
        pdf_verified = render_pdf_resume(resume, pdf_path, page_budget=page_budget)
        generated.append(pdf_name)

    if "docx" in formats:
        docx_name = f"{stem}.docx"
        docx_path = target_dir / docx_name
        render_docx_resume(resume, docx_path, page_budget=page_budget)
        generated.append(docx_name)

    (target_dir / "job_posting.json").write_text(
        json.dumps(job.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    (target_dir / "ats_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    (target_dir / "resume_snapshot.json").write_text(
        json.dumps(resume.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    generated.extend(["job_posting.json", "ats_report.json", "resume_snapshot.json"])

    return target_dir, generated, pdf_verified
