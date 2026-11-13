import { useMemo, useState } from "react";
import { api } from "../api";
import { createDefaultEmployers } from "../constants/tailoring";
import { LiveResumeSheet } from "./LiveResumeSheet";
import type {
  BootstrapEmployerInput,
  CanonicalResume,
  ResumeListResponse,
  ResumeRecordResponse,
  RoleTrackConfig,
} from "../types";

interface ResumePanelProps {
  resumeState: ResumeListResponse | null;
  roleTracks: RoleTrackConfig[];
  onRefresh: () => Promise<void>;
}

const emptyResume = (): CanonicalResume => ({
  contact: {
    full_name: "",
    email: "",
    phone: "",
    location: "",
    linkedin: "",
    github: "",
    portfolio: "",
  },
  summary: "",
  education: [
    {
      institution: "",
      degree: "",
      location: "",
      graduation_date: "",
      gpa: "",
      coursework: [],
    },
  ],
  experience: [
    {
      id: "exp-1",
      company: "",
      title: "",
      location: "",
      start_date: "",
      end_date: "Present",
      bullets: [
        {
          id: "exp-1-b1",
          text: "",
          provenance: "VERIFIED_BASE",
          approved: true,
          tags: [],
        },
      ],
    },
  ],
  projects: [],
  certifications: [],
  skills: [
    { category: "Languages", items: [] },
    { category: "Systems & Cloud", items: [] },
  ],
});

export function ResumePanel({
  resumeState,
  roleTracks,
  onRefresh,
}: ResumePanelProps) {
  const resumes = resumeState?.resumes ?? [];
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [name, setName] = useState("Primary Base Resume");
  const [roleTrack, setRoleTrack] = useState(roleTracks[0]?.id || "senior_swe");
  const [isBase, setIsBase] = useState(true);
  const [form, setForm] = useState<CanonicalResume>(emptyResume);

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState("Uploaded Base Resume");
  const [uploadRole, setUploadRole] = useState(roleTracks[0]?.id || "senior_swe");
  const [uploadBase, setUploadBase] = useState(true);
  const [showUploadBox, setShowUploadBox] = useState(false);
  const [showBootstrapBox, setShowBootstrapBox] = useState(false);
  const [bootName, setBootName] = useState("Alex Rivera");
  const [bootEmail, setBootEmail] = useState("alex.rivera.eng@example.com");
  const [bootLocation, setBootLocation] = useState("New York, NY");
  const [bootRole, setBootRole] = useState("senior_swe");
  const [bootYears, setBootYears] = useState(5);
  const [bootSkills, setBootSkills] = useState("");
  const [bootEmployers, setBootEmployers] = useState<BootstrapEmployerInput[]>(() =>
    createDefaultEmployers()
  );
  const [bootGradDegree, setBootGradDegree] = useState("");
  const [bootUndergradDegree, setBootUndergradDegree] = useState("");
  const [bootBulletsPerExp, setBootBulletsPerExp] = useState(5);
  const [bootProjectsCount, setBootProjectsCount] = useState(2);
  const [bootPageBudget, setBootPageBudget] = useState(1.5);
  const [bootModeBusy, setBootModeBusy] = useState<"ollama" | "fallback" | null>(null);
  const [previewResumeId, setPreviewResumeId] = useState<number | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const groupedByRole = useMemo(() => {
    const groups: Record<string, ResumeRecordResponse[]> = {};
    for (const r of resumes) {
      if (!groups[r.role_track]) groups[r.role_track] = [];
      groups[r.role_track].push(r);
    }
    const orderedKeys = [
      ...roleTracks.map((t) => t.id).filter((id) => groups[id]?.length),
      ...Object.keys(groups).filter((id) => !roleTracks.some((t) => t.id === id)),
    ];
    return orderedKeys.map((roleId) => ({
      roleId,
      roleLabel: roleTracks.find((t) => t.id === roleId)?.display_name || roleId,
      items: groups[roleId] || [],
    }));
  }, [resumes, roleTracks]);

  const startNewResume = (presetRole?: string) => {
    setEditingId(null);
    setName("Base Resume");
    setRoleTrack(presetRole || roleTracks[0]?.id || "senior_swe");
    setIsBase(true);
    setForm(emptyResume());
    setEditorOpen(true);
    setError(null);
    setNotice(null);
  };

  const openEditResume = (item: ResumeRecordResponse) => {
    setEditingId(item.id);
    setName(item.name);
    setRoleTrack(item.role_track);
    setIsBase(item.is_base);
    setForm(JSON.parse(JSON.stringify(item.content)) as CanonicalResume);
    setEditorOpen(true);
    setError(null);
    setNotice(null);
  };

  const handleSaveForm = async () => {
    if (!form.contact.full_name.trim()) {
      setError("Full Name is required before saving.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const cleaned: CanonicalResume = {
        ...form,
        experience: form.experience.filter((e) => e.company.trim() || e.title.trim()),
        education: form.education.filter((e) => e.institution.trim() || e.degree.trim()),
        certifications: form.certifications.filter((c) => c.name.trim()),
        skills: form.skills.filter((s) => s.category.trim() && s.items.length > 0),
      };
      if (editingId != null) {
        await api.updateResume(editingId, {
          name: name.trim() || "Base Resume",
          role_track: roleTrack,
          is_base: isBase,
          content: cleaned,
        });
        setNotice("Resume updated.");
      } else {
        await api.createResume({
          name: name.trim() || "Base Resume",
          role_track: roleTrack,
          is_base: isBase,
          content: cleaned,
        });
        setNotice("Base resume created.");
      }
      await onRefresh();
      setEditorOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save resume.");
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = async () => {
    if (!uploadFile) {
      setError("Choose a .pdf, .docx, .txt, or .tex file to upload.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.uploadResumeFile(
        uploadFile,
        uploadName.trim() || uploadFile.name.replace(/\.[^.]+$/, ""),
        uploadRole,
        uploadBase
      );
      setUploadFile(null);
      setShowUploadBox(false);
      setNotice("Resume uploaded and parsed cleanly.");
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleBootstrap = async (useOllama: boolean) => {
    setBusy(true);
    setBootModeBusy(useOllama ? "ollama" : "fallback");
    setError(null);
    setNotice(null);
    try {
      const skillsList = bootSkills
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const validEmployers = bootEmployers
        .filter((emp) => emp.company.trim().length > 0)
        .map((emp) => ({
          company: emp.company.trim(),
          title: emp.title?.trim() || null,
          location: emp.location?.trim() || null,
          start_date: emp.start_date?.trim() || null,
          end_date: emp.end_date?.trim() || null,
          bullets_count: emp.bullets_count || bootBulletsPerExp,
        }));
      const roleBulletCounts = validEmployers.map(
        (emp) => emp.bullets_count || bootBulletsPerExp
      );
      const res = await api.bootstrapResume({
        full_name: bootName.trim() || "Alex Rivera",
        email: bootEmail.trim() || "alex.rivera.eng@example.com",
        location: bootLocation.trim() || "New York, NY",
        role_track: bootRole || "senior_swe",
        years_experience: Math.max(1, Math.min(20, Number(bootYears) || 5)),
        focus_skills: skillsList,
        employers: validEmployers.length > 0 ? validEmployers : undefined,
        recent_company: validEmployers[0]?.company || null,
        prior_company: validEmployers[1]?.company || null,
        graduate_degree: bootGradDegree.trim() || null,
        undergrad_degree: bootUndergradDegree.trim() || null,
        bullets_per_experience: bootBulletsPerExp,
        bullets_per_role_counts: roleBulletCounts.length > 0 ? roleBulletCounts : null,
        projects_count: Math.max(2, bootProjectsCount),
        page_budget: bootPageBudget,
        use_llm: useOllama,
        save_as_base: true,
      });
      setShowBootstrapBox(false);
      setPreviewResumeId(res.resume.id);
      const notesTail = res.notes.length > 0 ? ` — ${res.notes[0]}` : "";
      setNotice(
        `Generated "${res.resume.name}" via ${
          res.model_used || "Structured Reasoning Script"
        } (${res.humanized_count} humanizer checks)${notesTail}`
      );
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Auto-generation failed.");
    } finally {
      setBusy(false);
      setBootModeBusy(null);
    }
  };

  const handleSetActive = async (item: ResumeRecordResponse) => {
    setBusy(true);
    try {
      await api.updateResume(item.id, {
        name: item.name,
        role_track: item.role_track,
        is_base: true,
        content: item.content,
      });
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to activate resume.");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (resumeId: number) => {
    setBusy(true);
    try {
      await api.deleteResume(resumeId);
      if (editingId === resumeId) {
        setEditorOpen(false);
        setEditingId(null);
      }
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete resume.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack-lg">
      <div className="card row-between">
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>Base Resumes</h2>
          <div className="muted">
            Organized by target role and city. Header location adapts per job.
          </div>
        </div>
        <div className="row-wrap">
          <button
            className="btn"
            onClick={() => {
              setShowBootstrapBox((v) => !v);
              setShowUploadBox(false);
            }}
          >
            {showBootstrapBox ? "Close Auto-Generator" : "Auto-Generate 5-Yr Base"}
          </button>
          <button
            className="btn"
            onClick={() => {
              setShowUploadBox((v) => !v);
              setShowBootstrapBox(false);
            }}
          >
            {showUploadBox ? "Close Upload" : "Upload PDF / DOCX / TEX"}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => startNewResume()}
          >
            + New Resume Box
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      {showBootstrapBox && (
        <div className="card stack-md">
          <div>
            <h3 style={{ margin: 0, fontSize: 15 }}>
              Auto-Generate Quantified 5-Year Generic Base Resume
            </h3>
            <div className="small-note">
              Enter minimal info below — creates a recruiter-ready Google XYZ resume humanized for ATS, optionally enhanced by your single local Ollama model.
            </div>
          </div>
          <div className="form-grid-3">
            <div>
              <label>Full Name</label>
              <input
                value={bootName}
                onChange={(e) => setBootName(e.target.value)}
                placeholder="Alex Rivera"
              />
            </div>
            <div>
              <label>Email</label>
              <input
                value={bootEmail}
                onChange={(e) => setBootEmail(e.target.value)}
                placeholder="alex.rivera.eng@example.com"
              />
            </div>
            <div>
              <label>Target City / State</label>
              <input
                value={bootLocation}
                onChange={(e) => setBootLocation(e.target.value)}
                placeholder="New York, NY"
              />
            </div>
          </div>
          <div className="form-grid-3">
            <div>
              <label>Target Role Track</label>
              <select value={bootRole} onChange={(e) => setBootRole(e.target.value)}>
                {roleTracks.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>Years of Experience</label>
              <input
                type="number"
                min={1}
                max={20}
                value={bootYears}
                onChange={(e) => setBootYears(Number(e.target.value) || 5)}
              />
            </div>
            <div>
              <label>Focus Skills (optional comma-separated)</label>
              <input
                value={bootSkills}
                onChange={(e) => setBootSkills(e.target.value)}
                placeholder="Python, Kubernetes, Kafka, AWS"
              />
            </div>
          </div>
          <div className="form-grid-3">
            <div>
              <label>Default Bullets / Role</label>
              <select
                value={bootBulletsPerExp}
                onChange={(e) => setBootBulletsPerExp(Number(e.target.value) || 5)}
              >
                {[3, 4, 5, 6, 7, 8].map((n) => (
                  <option key={n} value={n}>
                    {n} bullets / role
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>Projects Count (Min 2)</label>
              <select
                value={bootProjectsCount}
                onChange={(e) => setBootProjectsCount(Math.max(2, Number(e.target.value) || 2))}
              >
                {[2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n} Projects
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>Target Page Size</label>
              <select
                value={bootPageBudget}
                onChange={(e) => setBootPageBudget(Number(e.target.value) || 1.5)}
              >
                <option value={1}>1 Page (Tight Senior)</option>
                <option value={1.5}>1.5 Pages (Balanced)</option>
                <option value={2}>2 Pages (Detailed Senior)</option>
              </select>
            </div>
          </div>

          <div className="card-elevated stack-sm">
            <div className="row-between">
              <strong style={{ fontSize: 13.5 }}>
                Employers &amp; Employment Timeline ({bootEmployers.length})
              </strong>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() =>
                  setBootEmployers((prev) => [
                    ...prev,
                    {
                      company: "",
                      title: "Software Engineer",
                      location: bootLocation || "Austin, TX",
                      start_date: "Jan 2019",
                      end_date: "Feb 2021",
                      bullets_count: Math.max(4, bootBulletsPerExp - 1),
                    },
                  ])
                }
              >
                + Add Employer
              </button>
            </div>
            {bootEmployers.map((emp, idx) => (
              <div key={idx} className="form-grid-3" style={{ alignItems: "end" }}>
                <div>
                  <label>Company #{idx + 1}</label>
                  <input
                    value={emp.company}
                    onChange={(e) => {
                      const next = [...bootEmployers];
                      next[idx] = { ...emp, company: e.target.value };
                      setBootEmployers(next);
                    }}
                    placeholder="e.g. Amazon"
                  />
                </div>
                <div>
                  <label>Role Title</label>
                  <input
                    value={emp.title || ""}
                    onChange={(e) => {
                      const next = [...bootEmployers];
                      next[idx] = { ...emp, title: e.target.value };
                      setBootEmployers(next);
                    }}
                    placeholder="Senior Software Engineer"
                  />
                </div>
                <div className="row-wrap" style={{ flexWrap: "nowrap", gap: 6 }}>
                  <div style={{ flex: 1 }}>
                    <label>Start – End Dates</label>
                    <div className="row-wrap" style={{ flexWrap: "nowrap", gap: 4 }}>
                      <input
                        value={emp.start_date || ""}
                        onChange={(e) => {
                          const next = [...bootEmployers];
                          next[idx] = { ...emp, start_date: e.target.value };
                          setBootEmployers(next);
                        }}
                        placeholder="Jan 2023"
                      />
                      <input
                        value={emp.end_date || ""}
                        onChange={(e) => {
                          const next = [...bootEmployers];
                          next[idx] = { ...emp, end_date: e.target.value };
                          setBootEmployers(next);
                        }}
                        placeholder="Present"
                      />
                    </div>
                  </div>
                  <div style={{ width: 92 }}>
                    <label>Location</label>
                    <input
                      value={emp.location || ""}
                      onChange={(e) => {
                        const next = [...bootEmployers];
                        next[idx] = { ...emp, location: e.target.value };
                        setBootEmployers(next);
                      }}
                      placeholder="City, ST"
                    />
                  </div>
                  <div style={{ width: 72 }}>
                    <label>Bullets</label>
                    <select
                      value={emp.bullets_count || bootBulletsPerExp}
                      onChange={(e) => {
                        const next = [...bootEmployers];
                        next[idx] = { ...emp, bullets_count: Number(e.target.value) || 5 };
                        setBootEmployers(next);
                      }}
                    >
                      {[3, 4, 5, 6, 7, 8].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </div>
                  {bootEmployers.length > 1 && (
                    <button
                      type="button"
                      className="btn btn-sm btn-danger-ghost"
                      onClick={() =>
                        setBootEmployers((prev) => prev.filter((_, i) => i !== idx))
                      }
                      title="Remove employer"
                    >
                      &times;
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="form-grid-2">
            <div>
              <label>Graduate Degree (optional)</label>
              <input
                value={bootGradDegree}
                onChange={(e) => setBootGradDegree(e.target.value)}
                placeholder="Master of Science in Data Science (default)"
              />
            </div>
            <div>
              <label>Undergraduate Degree (optional)</label>
              <input
                value={bootUndergradDegree}
                onChange={(e) => setBootUndergradDegree(e.target.value)}
                placeholder="Bachelor of Science in Computer Science (default)"
              />
            </div>
          </div>
          <div className="row-between">
            <span className="small-note">
              Includes Summary, variable bullets per employer, {bootProjectsCount} Projects, Technical Skills &amp; Grad/Undergrad Education.
            </span>
            <div className="row-wrap">
              <button
                type="button"
                className="btn"
                onClick={() => void handleBootstrap(false)}
                disabled={busy}
              >
                {bootModeBusy === "fallback"
                  ? "Generating (Script)..."
                  : "Generate Without Ollama (Script)"}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void handleBootstrap(true)}
                disabled={busy}
              >
                {bootModeBusy === "ollama"
                  ? "Generating (Ollama)..."
                  : "Generate With Local Ollama"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showUploadBox && (
        <div className="card stack-md">
          <h3 style={{ margin: 0, fontSize: 15 }}>Upload Resume</h3>
          <div className="form-grid-3">
            <div>
              <label>Profile Name</label>
              <input
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
                placeholder="e.g. Seattle SWE Profile"
              />
            </div>
            <div>
              <label>Target Role Track</label>
              <select value={uploadRole} onChange={(e) => setUploadRole(e.target.value)}>
                {roleTracks.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>File</label>
              <input
                type="file"
                accept=".pdf,.docx,.txt,.md,.tex"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
            </div>
          </div>
          <div className="row-between">
            <label className="row-wrap" style={{ margin: 0, cursor: "pointer" }}>
              <input
                type="checkbox"
                style={{ width: "auto" }}
                checked={uploadBase}
                onChange={(e) => setUploadBase(e.target.checked)}
              />
              Set as Active Base Resume for this Role Track
            </label>
            <button
              className="btn btn-primary"
              onClick={() => void handleUpload()}
              disabled={busy}
            >
              {busy ? "Uploading..." : "Upload & Parse"}
            </button>
          </div>
        </div>
      )}

      {groupedByRole.length === 0 ? (
        <div className="card stack-sm" style={{ textAlign: "center", padding: 36 }}>
          <h3 style={{ margin: 0 }}>No Base Resumes Added Yet</h3>
          <p className="muted" style={{ margin: 0 }}>
            Upload your existing resume or click "+ New Resume Box" to create one for Senior SWE, AI Engineer, FDE, or other tracks.
          </p>
        </div>
      ) : (
        groupedByRole.map((group) => (
          <div key={group.roleId} className="resume-role-section">
            <div className="row-between">
              <div className="row-wrap">
                <h3 style={{ margin: 0, fontSize: 16 }}>{group.roleLabel}</h3>
                <span className="pill">{group.items.length} profile(s)</span>
              </div>
              <button
                className="btn btn-sm"
                onClick={() => startNewResume(group.roleId)}
              >
                + Add {group.roleLabel} Box
              </button>
            </div>

            <div className="resume-box-grid">
              {group.items.map((item) => {
                const loc = item.content.contact.location?.trim() || "Unspecified Location";
                const expCount = item.content.experience.length;
                const eduCount = item.content.education.length;
                const certCount = item.content.certifications.length;
                return (
                  <div
                    key={item.id}
                    className={`resume-box-card ${item.is_base ? "active" : ""}`}
                    onClick={() => openEditResume(item)}
                  >
                    <div className="stack-sm">
                      <div className="row-between">
                        <strong style={{ fontSize: 15 }}>{item.name}</strong>
                        {item.is_base ? (
                          <span className="pill pill-blue">Active Base</span>
                        ) : (
                          <span className="pill">Context</span>
                        )}
                      </div>
                      <div className="row-wrap">
                        <span className="pill pill-green">{loc}</span>
                        <span className="pill">{expCount} exp</span>
                        <span className="pill">{eduCount} edu</span>
                        {certCount > 0 && <span className="pill">{certCount} cert</span>}
                      </div>
                      <div className="small-note">
                        {item.content.contact.full_name || "No name"}
                        {item.source_filename ? ` · ${item.source_filename}` : ""}
                      </div>
                    </div>

                    <div className="row-between" onClick={(e) => e.stopPropagation()}>
                      {!item.is_base && (
                        <button
                          className="btn btn-sm"
                          onClick={() => void handleSetActive(item)}
                          disabled={busy}
                        >
                          Set Active
                        </button>
                      )}
                      <button
                        className="btn btn-sm"
                        onClick={() =>
                          setPreviewResumeId((prev) => (prev === item.id ? null : item.id))
                        }
                      >
                        {previewResumeId === item.id ? "Hide Preview" : "Preview"}
                      </button>
                      <button
                        className="btn btn-sm"
                        onClick={() => openEditResume(item)}
                      >
                        Edit
                      </button>
                      <button
                        className="btn btn-sm btn-danger-ghost"
                        onClick={() => void handleDelete(item.id)}
                        disabled={busy}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))
      )}

      {previewResumeId != null &&
        resumeState?.resumes.find((r) => r.id === previewResumeId) && (
          <div className="card stack-md">
            <div className="row-between">
              <strong style={{ fontSize: 15 }}>
                Resume Preview:{" "}
                {resumeState.resumes.find((r) => r.id === previewResumeId)?.name}
              </strong>
              <button
                className="btn btn-sm"
                onClick={() => setPreviewResumeId(null)}
              >
                Close Preview
              </button>
            </div>
            <LiveResumeSheet
              resume={resumeState.resumes.find((r) => r.id === previewResumeId)!.content}
              titleLabel="Formatted ATS Base Resume"
            />
          </div>
        )}

      {editorOpen && (
        <div className="card stack-md">
          <div className="row-between">
            <h3 style={{ margin: 0, fontSize: 16 }}>
              {editingId != null ? `Edit Resume: ${name}` : "Create Base Resume"}
            </h3>
            <button className="btn btn-sm" onClick={() => setEditorOpen(false)}>
              Close Editor
            </button>
          </div>

          <div className="form-grid-3">
            <div>
              <label>Profile Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label>Target Role Track</label>
              <select value={roleTrack} onChange={(e) => setRoleTrack(e.target.value)}>
                {roleTracks.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", paddingBottom: 8 }}>
              <label className="row-wrap" style={{ margin: 0, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={isBase}
                  onChange={(e) => setIsBase(e.target.checked)}
                />
                Active Base Resume for Track
              </label>
            </div>
          </div>

          <div className="card-elevated stack-sm">
            <strong>Contact &amp; Location</strong>
            <div className="form-grid-3">
              <div>
                <label>Full Name *</label>
                <input
                  value={form.contact.full_name}
                  onChange={(e) =>
                    setForm({ ...form, contact: { ...form.contact, full_name: e.target.value } })
                  }
                />
              </div>
              <div>
                <label>Base Location (City, State)</label>
                <input
                  value={form.contact.location}
                  onChange={(e) =>
                    setForm({ ...form, contact: { ...form.contact, location: e.target.value } })
                  }
                  placeholder="Seattle, WA"
                />
              </div>
              <div>
                <label>Email</label>
                <input
                  value={form.contact.email}
                  onChange={(e) =>
                    setForm({ ...form, contact: { ...form.contact, email: e.target.value } })
                  }
                />
              </div>
              <div>
                <label>Phone</label>
                <input
                  value={form.contact.phone}
                  onChange={(e) =>
                    setForm({ ...form, contact: { ...form.contact, phone: e.target.value } })
                  }
                />
              </div>
              <div>
                <label>LinkedIn</label>
                <input
                  value={form.contact.linkedin}
                  onChange={(e) =>
                    setForm({ ...form, contact: { ...form.contact, linkedin: e.target.value } })
                  }
                />
              </div>
              <div>
                <label>GitHub / Portfolio</label>
                <input
                  value={form.contact.github}
                  onChange={(e) =>
                    setForm({ ...form, contact: { ...form.contact, github: e.target.value } })
                  }
                />
              </div>
            </div>
          </div>

          <div className="card-elevated stack-sm">
            <label>Professional Summary</label>
            <textarea
              rows={2}
              value={form.summary || ""}
              onChange={(e) => setForm({ ...form, summary: e.target.value })}
            />
          </div>

          <div className="card-elevated stack-md">
            <div className="row-between">
              <strong>Work Experience</strong>
              <button
                className="btn btn-sm"
                onClick={() =>
                  setForm({
                    ...form,
                    experience: [
                      ...form.experience,
                      {
                        id: `exp-${form.experience.length + 1}`,
                        company: "",
                        title: "",
                        location: "",
                        start_date: "",
                        end_date: "",
                        bullets: [
                          {
                            id: `exp-${form.experience.length + 1}-b1`,
                            text: "",
                            provenance: "VERIFIED_BASE",
                            approved: true,
                            tags: [],
                          },
                        ],
                      },
                    ],
                  })
                }
              >
                + Add Experience
              </button>
            </div>
            {form.experience.map((exp, idx) => (
              <div key={exp.id || idx} className="card stack-sm">
                <div className="form-grid-3">
                  <div>
                    <label>Company</label>
                    <input
                      value={exp.company}
                      onChange={(e) => {
                        const next = [...form.experience];
                        next[idx] = { ...exp, company: e.target.value };
                        setForm({ ...form, experience: next });
                      }}
                    />
                  </div>
                  <div>
                    <label>Title</label>
                    <input
                      value={exp.title}
                      onChange={(e) => {
                        const next = [...form.experience];
                        next[idx] = { ...exp, title: e.target.value };
                        setForm({ ...form, experience: next });
                      }}
                    />
                  </div>
                  <div>
                    <label>Dates</label>
                    <div className="row-wrap">
                      <input
                        style={{ flex: 1 }}
                        placeholder="Start"
                        value={exp.start_date}
                        onChange={(e) => {
                          const next = [...form.experience];
                          next[idx] = { ...exp, start_date: e.target.value };
                          setForm({ ...form, experience: next });
                        }}
                      />
                      <input
                        style={{ flex: 1 }}
                        placeholder="End"
                        value={exp.end_date}
                        onChange={(e) => {
                          const next = [...form.experience];
                          next[idx] = { ...exp, end_date: e.target.value };
                          setForm({ ...form, experience: next });
                        }}
                      />
                    </div>
                  </div>
                </div>
                <label>Bullets (one per line)</label>
                <textarea
                  rows={3}
                  value={exp.bullets.map((b) => b.text).join("\n")}
                  onChange={(e) => {
                    const lines = e.target.value.split("\n");
                    const next = [...form.experience];
                    next[idx] = {
                      ...exp,
                      bullets: lines.map((line, bIdx) => ({
                        id: exp.bullets[bIdx]?.id || `${exp.id || idx}-b${bIdx + 1}`,
                        text: line,
                        provenance: exp.bullets[bIdx]?.provenance || "VERIFIED_BASE",
                        approved: true,
                        tags: exp.bullets[bIdx]?.tags || [],
                      })),
                    };
                    setForm({ ...form, experience: next });
                  }}
                />
              </div>
            ))}
          </div>

          <div className="form-grid-2">
            <div className="card-elevated stack-sm">
              <div className="row-between">
                <strong>Education</strong>
                <button
                  className="btn btn-sm"
                  onClick={() =>
                    setForm({
                      ...form,
                      education: [
                        ...form.education,
                        {
                          institution: "",
                          degree: "",
                          location: "",
                          graduation_date: "",
                          gpa: "",
                          coursework: [],
                        },
                      ],
                    })
                  }
                >
                  + Add Degree
                </button>
              </div>
              {form.education.map((edu, idx) => (
                <div key={idx} className="stack-sm" style={{ borderTop: idx > 0 ? "1px solid var(--border-subtle)" : undefined, paddingTop: idx > 0 ? 8 : 0 }}>
                  <input
                    placeholder="Institution"
                    value={edu.institution}
                    onChange={(e) => {
                      const next = [...form.education];
                      next[idx] = { ...edu, institution: e.target.value };
                      setForm({ ...form, education: next });
                    }}
                  />
                  <div className="row-wrap">
                    <input
                      style={{ flex: 2 }}
                      placeholder="Degree (e.g. MS Computer Science)"
                      value={edu.degree}
                      onChange={(e) => {
                        const next = [...form.education];
                        next[idx] = { ...edu, degree: e.target.value };
                        setForm({ ...form, education: next });
                      }}
                    />
                    <input
                      style={{ flex: 1 }}
                      placeholder="Grad Date"
                      value={edu.graduation_date}
                      onChange={(e) => {
                        const next = [...form.education];
                        next[idx] = { ...edu, graduation_date: e.target.value };
                        setForm({ ...form, education: next });
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className="card-elevated stack-sm">
              <div className="row-between">
                <strong>Certifications</strong>
                <button
                  className="btn btn-sm"
                  onClick={() =>
                    setForm({
                      ...form,
                      certifications: [
                        ...form.certifications,
                        { name: "", issuer: "", date: "", credential_url: "" },
                      ],
                    })
                  }
                >
                  + Add Cert
                </button>
              </div>
              {form.certifications.map((cert, idx) => (
                <div key={idx} className="form-grid-3">
                  <input
                    placeholder="Certification Name"
                    value={cert.name}
                    onChange={(e) => {
                      const next = [...form.certifications];
                      next[idx] = { ...cert, name: e.target.value };
                      setForm({ ...form, certifications: next });
                    }}
                  />
                  <input
                    placeholder="Issuer"
                    value={cert.issuer}
                    onChange={(e) => {
                      const next = [...form.certifications];
                      next[idx] = { ...cert, issuer: e.target.value };
                      setForm({ ...form, certifications: next });
                    }}
                  />
                  <input
                    placeholder="Date"
                    value={cert.date}
                    onChange={(e) => {
                      const next = [...form.certifications];
                      next[idx] = { ...cert, date: e.target.value };
                      setForm({ ...form, certifications: next });
                    }}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="card-elevated stack-sm">
            <strong>Technical Skills</strong>
            {form.skills.map((cat, idx) => (
              <div key={idx} className="form-grid-2">
                <input
                  value={cat.category}
                  onChange={(e) => {
                    const next = [...form.skills];
                    next[idx] = { ...cat, category: e.target.value };
                    setForm({ ...form, skills: next });
                  }}
                />
                <input
                  value={cat.items.join(", ")}
                  onChange={(e) => {
                    const next = [...form.skills];
                    next[idx] = {
                      ...cat,
                      items: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    };
                    setForm({ ...form, skills: next });
                  }}
                  placeholder="Python, FastAPI, Docker, PostgreSQL"
                />
              </div>
            ))}
          </div>

          <div className="row-between">
            <span className="small-note">
              Saved to your profile workspace &amp; matched automatically during batch scoring.
            </span>
            <button
              className="btn btn-primary"
              onClick={() => void handleSaveForm()}
              disabled={busy}
            >
              {busy ? "Saving..." : "Save Base Resume"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
