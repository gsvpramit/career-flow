"""Resume file parser (.pdf, .docx, .txt, .tex) and plain-text canonicalizer."""

from __future__ import annotations

import io
import re

from docx import Document
from pypdf import PdfReader

from backend.app.schemas.resume import (
    CanonicalResume,
    CertificationItem,
    ContactInfo,
    EducationItem,
    ExperienceBullet,
    ExperienceItem,
    ProjectItem,
    SkillCategory,
)

SECTION_ALIASES = {
    "education": "education",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "projects": "projects",
    "certifications": "certifications",
    "certificates": "certifications",
    "licenses certifications": "certifications",
    "licenses and certifications": "certifications",
    "technical skills": "skills",
    "skills": "skills",
    "summary": "summary",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/|github\.com/)[^\s|,;]+", re.I)
DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4})\s*[-–—to]+\s*"
    r"(Present|Current|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4})",
    re.IGNORECASE,
)


def extract_text_from_upload(filename: str, content_bytes: bytes) -> tuple[str, str]:
    """Return (source_type, extracted_plain_text) for .pdf, .docx, .tex, or .txt/.md."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "pdf", "\n".join(pages).strip()

    if lower.endswith(".docx"):
        doc = Document(io.BytesIO(content_bytes))
        lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "docx", "\n".join(lines)

    decoded = content_bytes.decode("utf-8", errors="replace")
    if lower.endswith(".tex"):
        stripped = re.sub(r"%.*", "", decoded)
        stripped = re.sub(r"\\(?:textbf|textit|underline|href\{[^}]*\})\{([^}]*)\}", r"\1", stripped)
        stripped = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", stripped)
        stripped = stripped.replace("{", " ").replace("}", " ")
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in stripped.splitlines()]
        return "tex", "\n".join(ln for ln in lines if ln)

    return "text", decoded.strip()


def _parse_contact(lines: list[str]) -> ContactInfo:
    header_text = "\n".join(lines[:6])
    full_name = lines[0].strip() if lines else "Candidate Name"
    email_m = EMAIL_RE.search(header_text)
    phone_m = PHONE_RE.search(header_text)
    linkedin = ""
    github = ""
    for url_m in URL_RE.finditer(header_text):
        url_val = url_m.group(0)
        if "linkedin.com" in url_val.lower() and not linkedin:
            linkedin = url_val
        elif "github.com" in url_val.lower() and not github:
            github = url_val
    return ContactInfo(
        full_name=full_name[:120],
        email=email_m.group(0) if email_m else "",
        phone=phone_m.group(0) if phone_m else "",
        linkedin=linkedin,
        github=github,
    )


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^(?:[-*•\u2022]|\d+\.)\s+", line))


def _strip_bullet(line: str) -> str:
    return re.sub(r"^(?:[-*•\u2022]|\d+\.)\s+", "", line).strip()


def parse_text_to_canonical_resume(raw_text: str) -> CanonicalResume:
    """Heuristically convert extracted resume plain text into CanonicalResume."""
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    contact = _parse_contact(lines)

    sections: dict[str, list[str]] = {
        "education": [],
        "experience": [],
        "projects": [],
        "certifications": [],
        "skills": [],
        "summary": [],
    }
    current_section: str | None = None
    for ln in lines[1:]:
        normalized_heading = re.sub(r"[^a-z\s]", "", ln.lower()).strip()
        if len(ln) <= 40 and normalized_heading in SECTION_ALIASES:
            current_section = SECTION_ALIASES[normalized_heading]
            continue
        if current_section:
            sections[current_section].append(ln)

    experience_items: list[ExperienceItem] = []
    current_exp: ExperienceItem | None = None
    for ln in sections["experience"]:
        if _is_bullet(ln):
            bullet_text = _strip_bullet(ln)
            if current_exp is None:
                current_exp = ExperienceItem(
                    id="exp_1",
                    company="Prior Experience",
                    title="Engineer",
                )
                experience_items.append(current_exp)
            current_exp.bullets.append(
                ExperienceBullet(
                    id=f"{current_exp.id}_b{len(current_exp.bullets) + 1}",
                    text=bullet_text,
                    provenance="VERIFIED_BASE",
                )
            )
        else:
            date_m = DATE_RANGE_RE.search(ln)
            cleaned_header = DATE_RANGE_RE.sub("", ln).strip(" |,-")
            parts = [p.strip() for p in re.split(r"\s*[|—–@]\s*|\s+at\s+", cleaned_header) if p.strip()]
            title = parts[0] if parts else cleaned_header or "Senior Engineer"
            company = parts[1] if len(parts) > 1 else "Company"
            if current_exp is not None and not current_exp.bullets and current_exp.company == "Company":
                current_exp.company = cleaned_header
                continue
            current_exp = ExperienceItem(
                id=f"exp_{len(experience_items) + 1}",
                company=company,
                title=title,
                start_date=date_m.group(1) if date_m else "",
                end_date=date_m.group(2) if date_m else "",
            )
            experience_items.append(current_exp)

    education_items: list[EducationItem] = []
    edu_lines = sections["education"]
    idx = 0
    while idx < len(edu_lines):
        line = edu_lines[idx]
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            education_items.append(
                EducationItem(
                    institution=parts[0],
                    degree=parts[1] if len(parts) > 1 else "Degree",
                    graduation_date=parts[2] if len(parts) > 2 else "",
                )
            )
            idx += 1
        else:
            degree = edu_lines[idx + 1] if idx + 1 < len(edu_lines) else "B.S. in Computer Science"
            education_items.append(EducationItem(institution=line, degree=degree))
            idx += 2

    certification_items: list[CertificationItem] = []
    for ln in sections["certifications"]:
        clean = _strip_bullet(ln) if _is_bullet(ln) else ln
        parts = [p.strip() for p in clean.split("|")]
        if parts and parts[0]:
            certification_items.append(
                CertificationItem(
                    name=parts[0],
                    issuer=parts[1] if len(parts) > 1 else "",
                    date=parts[2] if len(parts) > 2 else "",
                    credential_url=parts[3] if len(parts) > 3 else "",
                )
            )

    project_items: list[ProjectItem] = []
    current_proj: ProjectItem | None = None
    for ln in sections["projects"]:
        if _is_bullet(ln):
            if current_proj is None:
                current_proj = ProjectItem(id="proj_1", name="Featured Project")
                project_items.append(current_proj)
            current_proj.bullets.append(
                ExperienceBullet(
                    id=f"{current_proj.id}_b{len(current_proj.bullets) + 1}",
                    text=_strip_bullet(ln),
                    provenance="VERIFIED_BASE",
                )
            )
        else:
            parts = [p.strip() for p in ln.split("|", 1)]
            stack = [s.strip() for s in parts[1].split(",") if s.strip()] if len(parts) > 1 else []
            current_proj = ProjectItem(
                id=f"proj_{len(project_items) + 1}",
                name=parts[0],
                tech_stack=stack,
            )
            project_items.append(current_proj)

    skill_categories: list[SkillCategory] = []
    for ln in sections["skills"]:
        if ":" in ln:
            cat, rest = ln.split(":", 1)
            items = [s.strip() for s in re.split(r"[,;•]", rest) if s.strip()]
            if items:
                skill_categories.append(SkillCategory(category=cat.strip(), items=items))
        else:
            items = [s.strip() for s in re.split(r"[,;•]", ln) if s.strip()]
            if items:
                skill_categories.append(SkillCategory(category="Technical Skills", items=items))

    return CanonicalResume(
        contact=contact,
        education=education_items,
        experience=experience_items,
        projects=project_items,
        certifications=certification_items,
        skills=skill_categories,
        summary="\n".join(sections["summary"]) if sections["summary"] else None,
    )


def parse_uploaded_resume(filename: str, content_bytes: bytes) -> tuple[str, CanonicalResume, str]:
    """Parse uploaded resume bytes into (source_type, CanonicalResume, raw_text)."""
    source_type, raw_text = extract_text_from_upload(filename, content_bytes)
    canonical = parse_text_to_canonical_resume(raw_text)
    return source_type, canonical, raw_text


def resume_to_plain_text(resume: CanonicalResume) -> str:
    """Flatten CanonicalResume into searchable plain text for ATS scoring."""
    parts: list[str] = [
        resume.contact.full_name,
        resume.contact.email,
        resume.contact.phone,
        resume.contact.location,
        resume.contact.linkedin,
        resume.contact.github,
    ]
    if resume.summary:
        parts.append(resume.summary)
    for edu in resume.education:
        parts.extend([edu.institution, edu.degree, edu.graduation_date, *edu.coursework])
    for exp in resume.experience:
        parts.extend([exp.company, exp.title, exp.location, f"{exp.start_date} - {exp.end_date}"])
        parts.extend(b.text for b in exp.bullets if b.approved)
    for proj in resume.projects:
        parts.extend([proj.name, *proj.tech_stack])
        parts.extend(b.text for b in proj.bullets if b.approved)
    for cert in resume.certifications:
        parts.extend([cert.name, cert.issuer, cert.date])
    for cat in resume.skills:
        parts.append(f"{cat.category}: {', '.join(cat.items)}")
    return "\n".join(p for p in parts if p)
