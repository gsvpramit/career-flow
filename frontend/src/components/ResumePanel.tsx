import { useMemo, useState } from "react";
import { api } from "../api";
import type {
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
            onClick={() => setShowUploadBox((v) => !v)}
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

      {showUploadBox && (
        <div className="card stack-md">
          <h3 style={{ margin: 0, fontSize: 15 }}>Upload Resume File (.pdf, .docx, .txt, .tex)</h3>
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
            <strong>Candidate Contact & Target Location</strong>
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
            <strong>Technical Skills (comma-separated items per category)</strong>
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
              Saved locally to SQLite & matched automatically during batch scoring.
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
