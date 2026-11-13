import { useState } from "react";

export interface BulletBankItem {
  id: string;
  source: string;
  category: "Intuit (Big Data & AI)" | "AWS (Bifrost & Streaming)" | "Amazon (Associate & Security)" | "Quest Global / WebileApps" | "Authentic Projects";
  roleOrProject: string;
  bullet: string;
  techTags: string[];
}

export const CANDIDATE_BULLET_BANK: BulletBankItem[] = [
  // Intuit
  {
    id: "bank_intuit_1",
    source: "Intuit Resume",
    category: "Intuit (Big Data & AI)",
    roleOrProject: "Software Engineer 2 (Big Data Engineering)",
    bullet: "Acted as tech lead for core applications, guiding architectural decisions, governing implementation, and collaborating with product owners and clients to deliver scalable solutions for real-time business needs.",
    techTags: ["Tech Lead", "Architecture", "Agile"],
  },
  {
    id: "bank_intuit_2",
    source: "Intuit Resume",
    category: "Intuit (Big Data & AI)",
    roleOrProject: "Software Engineer 2 (Big Data Engineering)",
    bullet: "Led a team of 5+ engineers to design and deliver high-severity, production-grade data pipelines using PySpark, Airflow, and BPP orchestration, enabling reliable real-time and batch data delivery for reporting, forecasting, and executive analytics.",
    techTags: ["PySpark", "Apache Airflow", "Data Pipelines"],
  },
  {
    id: "bank_intuit_3",
    source: "Intuit Resume",
    category: "Intuit (Big Data & AI)",
    roleOrProject: "Software Engineer 2 (Big Data Engineering)",
    bullet: "Built scalable data pipelines using an in-house PySpark framework (Quick ETL) to ingest, transform, and stage data in Amazon S3, followed by structured loading into Amazon Redshift for downstream analytics.",
    techTags: ["PySpark", "Amazon Redshift", "Amazon S3"],
  },
  {
    id: "bank_intuit_4",
    source: "Intuit Resume",
    category: "Intuit (Big Data & AI)",
    roleOrProject: "Software Engineer 2 (Big Data Engineering)",
    bullet: "Developed an AI Agent using Python that autonomously assists on-call engineers by root-causing production alerts—extracting Jira metadata, querying pipeline details, retrieving logs from EMR Serverless, and providing actionable solutions without SME intervention.",
    techTags: ["Python", "AI Agent", "EMR Serverless", "MCP"],
  },
  {
    id: "bank_intuit_5",
    source: "Intuit Resume",
    category: "Intuit (Big Data & AI)",
    roleOrProject: "Software Engineer 2 (Big Data Engineering)",
    bullet: "Built an AI agent that converts Technical Requirements documents into production-ready pipeline logic—automating SQL generation, partial ETL development using PySpark, scheduling, and provisioning EMR Serverless environments.",
    techTags: ["Agentic AI", "SQL Generation", "PySpark"],
  },
  {
    id: "bank_intuit_6",
    source: "Intuit Resume",
    category: "Intuit (Big Data & AI)",
    roleOrProject: "Software Engineer 2 (Big Data Engineering)",
    bullet: "Improved performance of multiple reporting pipelines by 60% through optimization of PySpark code, fine-tuning Spark configurations, and leveraging AWS EMR Serverless and S3 for efficient data processing.",
    techTags: ["PySpark", "Performance Tuning", "AWS EMR"],
  },
  {
    id: "bank_intuit_7",
    source: "Intuit Resume",
    category: "Intuit (Big Data & AI)",
    roleOrProject: "Software Engineer 2 (Big Data Engineering)",
    bullet: "Optimized Spark-based data pipelines by tuning job configurations and leveraging efficient Spark properties, resulting in 15% cost savings and improved runtime performance across large-scale ETL jobs on AWS EMR Serverless.",
    techTags: ["Apache Spark", "Cost Optimization", "AWS"],
  },
  // AWS
  {
    id: "bank_aws_1",
    source: "AWS Resume",
    category: "AWS (Bifrost & Streaming)",
    roleOrProject: "Software Development Engineer (AWS)",
    bullet: "Led a team of 5 engineers in orchestrating Bifrost, a data pipeline framework on AWS Cloud Development Kit (CDK) using AWS Glue, Lambda, S3, IAM, Step Functions, and CloudWatch, saving 80% build time for pipeline creation.",
    techTags: ["AWS CDK", "AWS Glue", "AWS Lambda", "Step Functions"],
  },
  {
    id: "bank_aws_2",
    source: "AWS Resume",
    category: "AWS (Bifrost & Streaming)",
    roleOrProject: "Software Development Engineer (AWS)",
    bullet: "Implemented TypeScript-based CI/CD pipelines for DevOps, saving 70% development and monitoring effort with automated rollback gates and contract tests.",
    techTags: ["TypeScript", "CI/CD", "DevOps"],
  },
  {
    id: "bank_aws_3",
    source: "AWS Resume",
    category: "AWS (Bifrost & Streaming)",
    roleOrProject: "Software Development Engineer (AWS)",
    bullet: "Led the Data Lake Publisher SDLC using Apache Flink for real-time stream processing, Kafka for event ingestion, AWS Lambda for orchestration, and S3 for storage—managing updates across 300+ data lake tables.",
    techTags: ["Apache Flink", "Kafka", "Data Lake", "AWS S3"],
  },
  {
    id: "bank_aws_4",
    source: "AWS Resume",
    category: "AWS (Bifrost & Streaming)",
    roleOrProject: "Software Development Engineer (AWS)",
    bullet: "Designed and deployed automated batch data pipelines using AWS EMR, managing millions of daily insertions and deletions with zero data corruption.",
    techTags: ["AWS EMR", "Batch Pipelines", "Big Data"],
  },
  {
    id: "bank_aws_5",
    source: "AWS Resume",
    category: "AWS (Bifrost & Streaming)",
    roleOrProject: "Software Development Engineer (AWS)",
    bullet: "Designed a notification engine for Slack reading change data capture (CDC) events on 300+ tables using AWS Lambda & SQS with idempotent replay semantics.",
    techTags: ["CDC", "AWS Lambda", "Amazon SQS"],
  },
  {
    id: "bank_aws_6",
    source: "AWS Resume",
    category: "AWS (Bifrost & Streaming)",
    roleOrProject: "Software Development Engineer (AWS)",
    bullet: "Designed and deployed containerized applications on Kubernetes using Amazon EKS, ensuring efficient orchestration and horizontal scalability in dynamic environments.",
    techTags: ["Kubernetes", "Amazon EKS", "Docker"],
  },
  // Amazon Associate & Security
  {
    id: "bank_amz_1",
    source: "Amazon SWE Resume",
    category: "Amazon (Associate & Security)",
    roleOrProject: "Software Development Engineer (Amazon)",
    bullet: "Engineered secure OAuth2/JWT-based authentication and authorization workflows using Spring Boot and AWS IAM for a global associate web platform supporting 1.5M+ employees across fulfillment operations.",
    techTags: ["Spring Boot", "OAuth2", "JWT", "AWS IAM"],
  },
  {
    id: "bank_amz_2",
    source: "Amazon SWE Resume",
    category: "Amazon (Associate & Security)",
    roleOrProject: "Software Development Engineer (Amazon)",
    bullet: "Delivered the Quebec francization initiative by localizing landing pages and employee tools into French using React and i18n/l10n frameworks, driving an estimated $5.5M business impact and unblocking launch readiness.",
    techTags: ["React", "TypeScript", "i18n"],
  },
  {
    id: "bank_amz_3",
    source: "Amazon SWE Resume",
    category: "Amazon (Associate & Security)",
    roleOrProject: "Software Development Engineer (Amazon)",
    bullet: "Built scalable React / Node.js web application features and RESTful API backend integrations for associate-facing platforms, improving usability, compliance, and reliability for high-volume internal users.",
    techTags: ["React", "Node.js", "RESTful API"],
  },
  {
    id: "bank_amz_4",
    source: "Amazon SWE Resume",
    category: "Amazon (Associate & Security)",
    roleOrProject: "Software Development Engineer (Amazon)",
    bullet: "Developed return-abuse prevention workflows for India marketplace using Java, AWS Lambda, and DynamoDB, enabling automated fee deductions and reducing abuse losses by 15–20% ($10M business impact).",
    techTags: ["Java", "AWS Lambda", "DynamoDB"],
  },
  {
    id: "bank_amz_5",
    source: "Amazon SWE Resume",
    category: "Amazon (Associate & Security)",
    roleOrProject: "Software Development Engineer (Amazon)",
    bullet: "Built provider-facing workflows for the AWS HealthAgent platform using Java, Spring Boot, and Amazon SQS/SNS, supporting appointment scheduling and real-time eligibility checks at peak volumes of ~4,000 TPS.",
    techTags: ["Java", "Spring Boot", "Amazon SQS", "4000 TPS"],
  },
  {
    id: "bank_amz_6",
    source: "Amazon SWE Resume",
    category: "Amazon (Associate & Security)",
    roleOrProject: "Software Development Engineer (Amazon)",
    bullet: "Improved patient authentication accuracy by implementing a ZIP code verification module in Java with Redis-cached lookup tables, increasing validation accuracy by 80%.",
    techTags: ["Java", "Redis", "Caching"],
  },
  // Quest Global / WebileApps
  {
    id: "bank_qg_1",
    source: "Quest Global Resume",
    category: "Quest Global / WebileApps",
    roleOrProject: "Software Development Engineer (Quest Global)",
    bullet: "Developed and enhanced Java / Spring Boot backend services for connected-vehicle platforms, supporting 2M+ vehicle interactions per day across distributed systems with 99.9% uptime and high availability.",
    techTags: ["Java", "Spring Boot", "High Availability", "99.9% Uptime"],
  },
  {
    id: "bank_qg_2",
    source: "Quest Global Resume",
    category: "Quest Global / WebileApps",
    roleOrProject: "Software Development Engineer (Quest Global)",
    bullet: "Built RESTful APIs and backend integrations using Java and Apache Kafka, enabling secure data exchange and reducing integration errors by 30% for 500K+ daily API calls.",
    techTags: ["Java", "Apache Kafka", "RESTful API"],
  },
  {
    id: "bank_qg_3",
    source: "Quest Global Resume",
    category: "Quest Global / WebileApps",
    roleOrProject: "Software Development Engineer (Quest Global)",
    bullet: "Improved backend performance by optimizing SQL queries, Hibernate ORM logic, and PostgreSQL database interactions, cutting average response time by 25% and server load by 20%.",
    techTags: ["PostgreSQL", "Hibernate", "SQL Optimization"],
  },
  {
    id: "bank_qg_4",
    source: "Quest Global Resume",
    category: "Quest Global / WebileApps",
    roleOrProject: "Software Development Engineer (Quest Global)",
    bullet: "Created 50+ reusable React components and responsive UI features using TypeScript and Redux for internal tools, reducing frontend development time by 40%.",
    techTags: ["React", "TypeScript", "Redux"],
  },
  {
    id: "bank_qg_5",
    source: "WebileApps Resume",
    category: "Quest Global / WebileApps",
    roleOrProject: "Data Engineer (WebileApps)",
    bullet: "Developed and optimized complex ETL pipelines using AWS Glue and Amazon S3 tailored to healthcare use cases, supporting high-throughput data ingestion and automated schema migrations for 500+ tables.",
    techTags: ["AWS Glue", "Amazon S3", "ETL"],
  },
  // Projects
  {
    id: "bank_proj_1",
    source: "Projects Portfolio",
    category: "Authentic Projects",
    roleOrProject: "Aiceberg — Production LLM Guardrail & Evaluation Engine",
    bullet: "Fine-tuned and optimized open-source LLMs (Llama, Mistral, Falcon) using PyTorch, CUDA, and AWS S3, onboarding custom data via LangChain loaders to boost model performance by 25% and reduce training iteration time by 40%.",
    techTags: ["PyTorch", "CUDA", "LangChain", "LLMs"],
  },
  {
    id: "bank_proj_2",
    source: "Projects Portfolio",
    category: "Authentic Projects",
    roleOrProject: "Aiceberg — Production LLM Guardrail & Evaluation Engine",
    bullet: "Engineered LLM security safeguards and evaluation pipelines using Transformers-based embeddings and ML classifiers to detect and block disallowed content before inference.",
    techTags: ["Transformers", "ML Classifiers", "Safety"],
  },
  {
    id: "bank_proj_3",
    source: "Projects Portfolio",
    category: "Authentic Projects",
    roleOrProject: "SmartClass — Distributed Serverless Event & Video Processing System",
    bullet: "Designed a smart classroom assistant using AWS Lambda to process 1,000+ classroom videos for facial recognition, extracting frames with FFmpeg and persisting event metadata in S3 and DynamoDB.",
    techTags: ["AWS Lambda", "FFmpeg", "DynamoDB", "Python"],
  },
  {
    id: "bank_proj_4",
    source: "Projects Portfolio",
    category: "Authentic Projects",
    roleOrProject: "SmartClass — Distributed Serverless Event & Video Processing System",
    bullet: "Built an elastic IaaS cloud image recognition application on AWS that dynamically auto-scales EC2 clusters based on request volume, deploying deep learning models via containerized workers.",
    techTags: ["AWS EC2", "Auto-scaling", "Docker"],
  },
  {
    id: "bank_proj_5",
    source: "Projects Portfolio",
    category: "Authentic Projects",
    roleOrProject: "Bifrost / QuickETL — Distributed Data Lakehouse Pipeline",
    bullet: "Designed and orchestrated automated high-throughput data pipelines using PySpark and Apache Flink for real-time Kafka event ingestion, managing updates across 300+ data lake tables.",
    techTags: ["PySpark", "Apache Flink", "Kafka", "Data Lake"],
  },
  {
    id: "bank_proj_6",
    source: "Projects Portfolio",
    category: "Authentic Projects",
    roleOrProject: "SentinelMesh — Autonomous Incident RCA & Telemetry Agent",
    bullet: "Developed an autonomous AI diagnostics agent utilizing Python and Model Context Protocol (MCP) to ingest production alerts, query pipeline telemetry, and root-cause EMR cluster incidents with zero manual triage.",
    techTags: ["Agentic AI", "MCP", "Python", "EMR Serverless"],
  },
];

interface CandidateBulletBankModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectBullet: (bulletText: string, tags: string[]) => void;
  targetRoleLabel?: string;
  existingBullets?: string[];
}

export function CandidateBulletBankModal({
  isOpen,
  onClose,
  onSelectBullet,
  targetRoleLabel = "Current Experience Role",
  existingBullets,
}: CandidateBulletBankModalProps) {
  const [selectedCat, setSelectedCat] = useState<string>("All");
  const [searchQuery, setSearchQuery] = useState("");

  if (!isOpen) return null;

  const categories = ["All", "Intuit (Big Data & AI)", "AWS (Bifrost & Streaming)", "Amazon (Associate & Security)", "Quest Global / WebileApps", "Authentic Projects"];

  const filtered = CANDIDATE_BULLET_BANK.filter((item) => {
    if (selectedCat !== "All" && item.category !== selectedCat) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchText = item.bullet.toLowerCase().includes(q);
      const matchRole = item.roleOrProject.toLowerCase().includes(q);
      const matchTag = item.techTags.some((t) => t.toLowerCase().includes(q));
      if (!matchText && !matchRole && !matchTag) return false;
    }
    return true;
  });

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "rgba(0, 0, 0, 0.75)",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        className="card-elevated stack-md"
        style={{
          width: "100%",
          maxWidth: 850,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          backgroundColor: "var(--bg-card)",
          borderRadius: 8,
          overflow: "hidden",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="row-between" style={{ padding: "12px 16px", borderBottom: "1px solid var(--border-subtle)" }}>
          <div>
            <strong style={{ fontSize: 16 }}>Bullet Bank</strong>
            <div className="small-note">
              Verified authentic achievements from your base resumes — insert into {targetRoleLabel} with 1 click.
            </div>
          </div>
          <button type="button" className="btn btn-sm btn-danger-ghost" onClick={onClose}>
            &times; Close
          </button>
        </div>

        <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border-subtle)", display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="text"
            placeholder="Search bullets by tech keyword (Kafka, PySpark, OAuth2, AWS, Docker)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ flex: 1, minWidth: 260 }}
          />
          <div className="row-wrap" style={{ gap: 4 }}>
            {categories.map((c) => (
              <button
                key={c}
                type="button"
                className={`btn btn-sm ${selectedCat === c ? "btn-primary" : ""}`}
                style={{ fontSize: 11.5, padding: "3px 8px" }}
                onClick={() => setSelectedCat(c)}
              >
                {c === "All" ? "All Sources" : c.split(" ")[0]}
              </button>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.length === 0 ? (
            <div className="muted" style={{ padding: 24, textAlign: "center" }}>
              No bullets matched your search.
            </div>
          ) : (
            filtered.map((item) => {
              const isAlreadyAdded = Boolean(
                existingBullets &&
                  existingBullets.some((b) => {
                    const bNorm = b.trim().toLowerCase();
                    const itemNorm = item.bullet.trim().toLowerCase();
                    return (
                      bNorm === itemNorm ||
                      (itemNorm.length >= 35 && bNorm.includes(itemNorm.slice(0, 35))) ||
                      (bNorm.length >= 35 && itemNorm.includes(bNorm.slice(0, 35)))
                    );
                  })
              );
              return (
                <div
                  key={item.id}
                  className="job-fact-card stack-xs"
                  style={{
                    border: "1px solid var(--border-subtle)",
                    borderRadius: 6,
                    padding: "10px 12px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  <div className="row-between" style={{ alignItems: "flex-start" }}>
                    <div>
                      <strong style={{ fontSize: 13, color: "var(--accent-blue)" }}>{item.roleOrProject}</strong>
                      <span className="small-note" style={{ marginLeft: 8 }}>({item.source})</span>
                      {isAlreadyAdded && (
                        <span className="pill pill-green" style={{ fontSize: 11, marginLeft: 8, fontWeight: 600 }}>
                          ✓ In Resume
                        </span>
                      )}
                    </div>
                    {isAlreadyAdded ? (
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        style={{
                          fontSize: 12,
                          padding: "3px 10px",
                          color: "var(--accent-green, #30d158)",
                          borderColor: "rgba(48, 209, 88, 0.45)",
                          cursor: "default",
                        }}
                        disabled
                      >
                        ✓ Added
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        style={{ fontSize: 12, padding: "3px 10px" }}
                        onClick={() => {
                          onSelectBullet(item.bullet, item.techTags);
                          onClose();
                        }}
                      >
                        + Insert Bullet
                      </button>
                    )}
                  </div>
                  <div style={{ fontSize: 13, lineHeight: 1.45 }}>{item.bullet}</div>
                  <div className="row-wrap" style={{ gap: 4 }}>
                    {item.techTags.map((t) => (
                      <span key={t} className="pill" style={{ fontSize: 11 }}>
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
