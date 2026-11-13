import { useState } from "react";
import { api } from "../api";
import type {
  ATSReport,
  CanonicalResume,
  EditHistoryEntry,
  ExportResponse,
  TailorPreviewResponse,
} from "../types";

interface LiveResumeSheetProps {
  resume: CanonicalResume;
  baseResume?: CanonicalResume | null;
  tailorPreview?: TailorPreviewResponse | null;
  liveReport?: ATSReport | null;
  exportResult?: ExportResponse | null;
  baseScore?: number | null;
  editHistory?: EditHistoryEntry[];
  pageBudget?: number;
  busy?: boolean;
  onExportFormat?: (formats: ("pdf" | "docx")[]) => void;
  onDownloaded?: (fileName: string) => void;
  titleLabel?: string;
  onRevertToStep?: (entry: EditHistoryEntry) => void;
}

export function LiveResumeSheet({
  resume,
  baseResume,
  tailorPreview,
  liveReport,
  exportResult,
  baseScore: baseScoreProp,
  editHistory = [],
  pageBudget,
  busy = false,
  onExportFormat,
  onDownloaded,
  titleLabel = "Resume Preview",
  onRevertToStep,
}: LiveResumeSheetProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const contact = resume.contact;
  const contactParts = [
    contact.location,
    contact.email,
    contact.phone,
    contact.linkedin,
    contact.github,
    contact.portfolio,
  ]
    .map((s) => (s || "").trim())
    .filter(Boolean);

  const effectiveScore =
    liveReport?.overall_score ?? tailorPreview?.tailored_score ?? null;
  const baseScore = baseScoreProp ?? tailorPreview?.base_score ?? null;
  const delta =
    effectiveScore != null && baseScore != null
      ? Number((effectiveScore - baseScore).toFixed(1))
      : null;
  const inBand =
    effectiveScore != null && effectiveScore >= 80 && effectiveScore <= 85;
  const aboveBand = effectiveScore != null && effectiveScore > 85;

  const pdfFile = exportResult?.generated_files.find((f) =>
    f.toLowerCase().endsWith(".pdf")
  );
  const docxFile = exportResult?.generated_files.find((f) =>
    f.toLowerCase().endsWith(".docx")
  );

  const modifiedBulletSet = new Set<string>();
  if (tailorPreview) {
    for (const exp of tailorPreview.experience_comparisons) {
      for (const b of exp.bullets) {
        if (b.status === "edited" || b.status === "polished") {
          modifiedBulletSet.add(b.tailored_text.trim());
        }
      }
    }
  }

  return (
    <div className="stack-sm">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", width: "100%", gap: "0.75rem" }}>
        <div className="stack-xs" style={{ flex: 1 }}>
          <div className="row-wrap" style={{ alignItems: "center", gap: "0.5rem" }}>
            <strong style={{ fontSize: 14 }}>{titleLabel}</strong>
            {baseScore != null && (
              <span className="pill pill-blue" style={{ fontSize: 12.5 }}>
                Base Resume ATS: {baseScore}%
              </span>
            )}
            {effectiveScore != null && (
              <span
                className={`pill ${
                  inBand ? "pill-green" : aboveBand ? "pill-blue" : "pill-amber"
                }`}
                style={{ fontSize: 12.5 }}
              >
                Tailored Resume ATS: {effectiveScore}%
                {delta != null && delta !== 0
                  ? ` (${delta > 0 ? "+" : ""}${delta}%)`
                  : ""}
                {inBand
                  ? " · 80–85% Sweet Spot"
                  : aboveBand
                  ? " · Over 85%"
                  : " · Below 80%"}
              </span>
            )}
            {liveReport && (
              <span className="pill">
                Est. {liveReport.estimated_pages} pg
                {pageBudget ? ` / ${pageBudget}p budget` : ""}
              </span>
            )}
          </div>
          <div className="small-note">
            Single-column ATS layout — updates live as you tailor and edit.
          </div>
        </div>

        <button
          type="button"
          className="btn btn-sm"
          style={{ marginLeft: "auto", flexShrink: 0 }}
          onClick={() => setIsCollapsed((v) => !v)}
        >
          {isCollapsed ? "▸ Expand Sheet" : "▾ Collapse Sheet"}
        </button>
      </div>

      {!isCollapsed && (
        <>
          {/* Numbered Edit History & ATS Progression Tracker */}
      {(baseScore != null || editHistory.length > 0) && (
        <div className="edit-history-card">
          <div className="row-between" style={{ marginBottom: 6 }}>
            <strong style={{ fontSize: 13 }}>
              Version History
            </strong>
            <span className="pill pill-blue" style={{ fontSize: 11 }}>
              {editHistory.length + (baseScore != null ? 1 : 0)} Versions Recorded
            </span>
          </div>
          <div className="edit-history-list">
            {baseScore != null && (
              <div
                className="edit-history-row"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  cursor: baseResume ? "pointer" : "default",
                  padding: "6px 10px",
                }}
                onClick={() => {
                  if (baseResume && onRevertToStep) {
                    onRevertToStep({
                      step: 1,
                      timestamp: new Date().toISOString(),
                      action: "Base Resume",
                      detail: "Original untailored base candidate profile",
                      atsScore: baseScore,
                      resumeSnapshot: baseResume,
                    });
                  }
                }}
                title={baseResume ? "Click to preview original untailored Base Resume (Step #1)" : undefined}
              >
                <span className="mono pill" style={{ fontWeight: 700, padding: "1px 6px" }}>#1</span>
                <span className="pill pill-blue" style={{ fontSize: 11 }}>Base Resume</span>
                <span className="muted" style={{ fontSize: 12, flex: 1 }}>Original base profile</span>
                <span className="pill" style={{ marginLeft: "auto", fontWeight: 700 }}>
                  {baseScore}% ATS
                </span>
                {baseResume && onRevertToStep && (
                  <span className="pill pill-green" style={{ fontSize: 11, cursor: "pointer" }}>
                    👁 View
                  </span>
                )}
              </div>
            )}
            {editHistory.map((entry, idx) => {
              const prevScore =
                idx > 0 ? editHistory[idx - 1].atsScore : baseScore ?? entry.atsScore;
              const deltaVal = Number((entry.atsScore - prevScore).toFixed(1));
              const canView = Boolean(entry.resumeSnapshot && onRevertToStep);
              return (
                <div
                  key={`${entry.step}_${entry.timestamp}_${idx}`}
                  className="edit-history-row"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    cursor: canView ? "pointer" : "default",
                    padding: "6px 10px",
                  }}
                  onClick={() => {
                    if (canView) onRevertToStep!(entry);
                  }}
                  title={canView ? `Click to preview version from Step #${entry.step}` : undefined}
                >
                  <span className="mono pill" style={{ fontWeight: 700, padding: "1px 6px" }}>
                    #{entry.step}
                  </span>
                  <span className="pill pill-blue" style={{ fontSize: 11 }}>
                    {entry.action.replace("Manual Edit", "Manual").replace("Tailored Full Resume", "Full Tailor")}
                  </span>
                  <span className="muted" style={{ fontSize: 12, flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {entry.detail}
                  </span>
                  <span
                    className={`pill ${
                      entry.atsScore >= 80 && entry.atsScore <= 85
                        ? "pill-green"
                        : entry.atsScore > 85
                        ? "pill-blue"
                        : "pill-amber"
                    }`}
                    style={{ marginLeft: "auto", fontWeight: 700 }}
                  >
                    {entry.atsScore}% ATS
                    {deltaVal !== 0 && (
                      <span className="mono" style={{ fontSize: 11, marginLeft: 4 }}>
                        ({deltaVal > 0 ? `+${deltaVal}` : deltaVal}%)
                      </span>
                    )}
                  </span>
                  {canView && (
                    <span className="pill pill-green" style={{ fontSize: 11, cursor: "pointer" }}>
                      👁 View
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Instant Download / Export Bar */}
      {(onExportFormat || exportResult) && (
        <div className="row-wrap" style={{ justifyContent: "space-between" }}>
          <div className="row-wrap">
            {exportResult && pdfFile ? (
              <a
                className="btn btn-sm btn-success"
                href={api.downloadArtifactUrl(exportResult.run_id, pdfFile)}
                download={pdfFile}
                onClick={() => onDownloaded?.(pdfFile)}
                title={`Download ${pdfFile}`}
              >
                Download PDF
              </a>
            ) : (
              onExportFormat && (
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={busy}
                  onClick={() => onExportFormat(["pdf", "docx"])}
                >
                  {busy ? "Generating..." : "Create & Download PDF"}
                </button>
              )
            )}

            {exportResult && docxFile ? (
              <a
                className="btn btn-sm btn-success"
                href={api.downloadArtifactUrl(exportResult.run_id, docxFile)}
                download={docxFile}
                onClick={() => onDownloaded?.(docxFile)}
                title={`Download ${docxFile}`}
              >
                Download DOCX
              </a>
            ) : (
              onExportFormat && (
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() => onExportFormat(["docx"])}
                >
                  Generate DOCX
                </button>
              )
            )}

            {exportResult && onExportFormat && (
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy}
                onClick={() => onExportFormat(["pdf", "docx"])}
                title="Re-export using your latest live edits"
              >
                {busy ? "Updating..." : "Re-Export Latest"}
              </button>
            )}
          </div>
          {exportResult && (pdfFile || docxFile) && (
            <span className="small-note mono">
              File: {pdfFile || docxFile}
            </span>
          )}
        </div>
      )}

      {/* White-paper formatted ATS preview sheet */}
      <article
        className={`resume-paper-sheet ${pageBudget === 1 ? "resume-paper-compact" : ""}`}
        aria-label="Formatted ATS Resume Preview"
      >
        <header className="resume-paper-header">
          <div className="resume-paper-name">{contact.full_name || "Candidate Name"}</div>
          {contactParts.length > 0 && (
            <div className="resume-paper-contact">{contactParts.join("  •  ")}</div>
          )}
        </header>

        {resume.summary && resume.summary.trim() && (
          <section className="resume-paper-section">
            <h4 className="resume-paper-heading">
              Summary
              {(Boolean(tailorPreview) || (baseResume && baseResume.summary !== resume.summary)) && (
                <span className="pill pill-green" style={{ fontSize: 10, marginLeft: 8, padding: "1px 6px", textTransform: "none", fontWeight: 600 }}>
                  Tailored
                </span>
              )}
            </h4>
            <p className={`resume-paper-text ${(Boolean(tailorPreview) || (baseResume && baseResume.summary !== resume.summary)) ? "resume-paper-bullet-tailored" : ""}`}>
              {resume.summary.trim()}
            </p>
          </section>
        )}

        {resume.experience.length > 0 && (
          <section className="resume-paper-section">
            <h4 className="resume-paper-heading">Experience</h4>
            <div className="resume-paper-stack">
              {resume.experience.map((exp, idx) => {
                const approvedBullets = exp.bullets.filter((b) => b.approved);
                const dates = [exp.start_date, exp.end_date].filter(Boolean).join(" – ");
                return (
                  <div key={exp.id || idx} className="resume-paper-role">
                    <div className="resume-paper-split">
                      <strong>{exp.title || "Software Engineer"}</strong>
                      <span>{dates}</span>
                    </div>
                    <div className="resume-paper-split resume-paper-sub">
                      <span>{exp.company}</span>
                      <span>{exp.location}</span>
                    </div>
                    {approvedBullets.length > 0 && (
                      <ul className="resume-paper-bullets">
                        {approvedBullets.map((b, bIdx) => {
                          const isTailored = modifiedBulletSet.has(b.text.trim()) || b.provenance === "REFRAMED" || b.provenance === "SUGGESTED_DRAFT";
                          return (
                            <li
                              key={b.id || bIdx}
                              className={isTailored ? "resume-paper-bullet-tailored" : undefined}
                            >
                              {b.text}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {resume.projects.length > 0 && (
          <section className="resume-paper-section">
            <h4 className="resume-paper-heading">Projects</h4>
            <div className="resume-paper-stack">
              {resume.projects.map((proj, pIdx) => {
                const isProjTailored = Boolean(
                  tailorPreview ||
                  proj.bullets.some((b) => b.provenance === "REFRAMED" || b.provenance === "SUGGESTED_DRAFT") ||
                  (baseResume && !baseResume.projects.some((bp) => bp.name.toLowerCase() === proj.name.toLowerCase()))
                );
                return (
                  <div key={proj.id || pIdx} className="resume-paper-role">
                    <div className="resume-paper-split">
                      <span>
                        <strong>{proj.name}</strong>
                        {proj.tech_stack.length > 0 ? ` | ${proj.tech_stack.join(", ")}` : ""}
                        {isProjTailored && (
                          <span className="pill pill-green" style={{ fontSize: 10, marginLeft: 6, padding: "1px 6px", textTransform: "none", fontWeight: 600 }}>
                            Tailored
                          </span>
                        )}
                      </span>
                      <span className="resume-paper-sub">{proj.link}</span>
                    </div>
                    {proj.bullets.filter((b) => b.approved).length > 0 && (
                      <ul className="resume-paper-bullets">
                        {proj.bullets
                          .filter((b) => b.approved)
                          .map((b, bIdx) => {
                            const isBulletTailored =
                              modifiedBulletSet.has(b.text.trim()) ||
                              b.provenance === "REFRAMED" ||
                              b.provenance === "SUGGESTED_DRAFT" ||
                              isProjTailored;
                            return (
                              <li
                                key={b.id || bIdx}
                                className={isBulletTailored ? "resume-paper-bullet-tailored" : undefined}
                              >
                                {b.text}
                              </li>
                            );
                          })}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {resume.skills.some((c) => c.items.length > 0) && (
          <section className="resume-paper-section">
            <h4 className="resume-paper-heading">
              Technical Skills
              {(tailorPreview?.added_jd_skills?.length ?? 0) > 0 && (
                <span className="pill pill-green" style={{ fontSize: 10, marginLeft: 8, padding: "1px 6px", textTransform: "none", fontWeight: 600 }}>
                  Tailored (+{tailorPreview?.added_jd_skills?.length ?? 0} skills added)
                </span>
              )}
            </h4>
            <div className="resume-paper-skills">
              {resume.skills
                .filter((c) => c.items.length > 0)
                .map((cat, cIdx) => (
                  <div key={`${cat.category}-${cIdx}`}>
                    <strong>{cat.category}:</strong>{" "}
                    {cat.items.map((item, itIdx) => {
                      const isAdded = tailorPreview?.added_jd_skills?.some((as) => as.toLowerCase() === item.toLowerCase());
                      return (
                        <span key={`${item}-${itIdx}`}>
                          {itIdx > 0 && ", "}
                          <span className={isAdded ? "resume-paper-bullet-tailored" : undefined} style={isAdded ? { fontWeight: 600 } : undefined}>
                            {item}
                          </span>
                        </span>
                      );
                    })}
                  </div>
                ))}
            </div>
          </section>
        )}

        {resume.education.length > 0 && (
          <section className="resume-paper-section">
            <h4 className="resume-paper-heading">Education</h4>
            <div className="resume-paper-stack">
              {resume.education.map((edu, eIdx) => (
                <div key={`${edu.institution}-${eIdx}`}>
                  <div className="resume-paper-split">
                    <strong>{edu.institution}</strong>
                    <span>{edu.location}</span>
                  </div>
                  <div className="resume-paper-split resume-paper-sub">
                    <span>
                      {edu.degree}
                      {edu.gpa ? ` (GPA: ${edu.gpa})` : ""}
                    </span>
                    <span>{edu.graduation_date}</span>
                  </div>
                  {edu.coursework && edu.coursework.length > 0 && (
                    <div className="resume-paper-coursework">
                      <strong>Coursework:</strong> {edu.coursework.join(", ")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {resume.certifications.length > 0 && (
          <section className="resume-paper-section">
            <h4 className="resume-paper-heading">Certifications</h4>
            {resume.certifications.map((cert, cIdx) => (
              <div key={`${cert.name}-${cIdx}`} className="resume-paper-split">
                <span>
                  <strong>{cert.name}</strong>
                  {cert.issuer ? ` — ${cert.issuer}` : ""}
                </span>
                <span className="resume-paper-sub">{cert.date}</span>
              </div>
            ))}
          </section>
        )}
      </article>
        </>
      )}
    </div>
  );
}
