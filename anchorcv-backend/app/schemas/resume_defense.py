from pydantic import BaseModel, Field


class ResumeDefenseClaim(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: str
    source: str
    priority: int = Field(ge=1, le=5)
    job_alignment: str = "not_applicable"
    matched_job_keywords: list[str] = Field(default_factory=list)
    related_ats_weaknesses: list[str] = Field(default_factory=list)


class ResumeDefenseQuestion(BaseModel):
    question_id: str
    claim_id: str
    question: str
    reasoning: str
    source_signals: list[str] = Field(default_factory=list)


class ResumeDefenseSignalSummary(BaseModel):
    jd_keywords: list[str] = Field(default_factory=list)
    ats_missing_keywords: list[str] = Field(default_factory=list)


class ResumeDefenseEvaluationResult(BaseModel):
    evaluation_id: str
    session_id: str
    claim_id: str
    question_id: str
    resume_claim: str
    interview_question: str
    evidence_strength: str
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    missing_evidence: list[str] = Field(default_factory=list)
    suggested_follow_up_question: str
    answer_excerpt: str
    evaluated_at: str


class ResumeDefenseMatrixEntry(BaseModel):
    claim_id: str
    question_id: str
    resume_claim: str
    related_job_requirement: str | None = None
    interview_question: str
    user_answer: str
    evidence_strength: str
    explanation: str
    missing_evidence: list[str] = Field(default_factory=list)
    suggested_follow_up_question: str
    recommendation: str


class ResumeDefenseMatrixSummary(BaseModel):
    total_claims: int = Field(ge=0)
    strong_claims: int = Field(ge=0)
    moderate_claims: int = Field(ge=0)
    weak_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)


class ResumeDefenseMatrixGroupedClaims(BaseModel):
    strong: list[ResumeDefenseMatrixEntry] = Field(default_factory=list)
    moderate: list[ResumeDefenseMatrixEntry] = Field(default_factory=list)
    weak: list[ResumeDefenseMatrixEntry] = Field(default_factory=list)
    unsupported: list[ResumeDefenseMatrixEntry] = Field(default_factory=list)


class ResumeDefenseMatrixResponse(BaseModel):
    session_id: str
    status: str
    generated_at: str
    summary: ResumeDefenseMatrixSummary
    narrative_summary: str
    grouped_claims: ResumeDefenseMatrixGroupedClaims
    entries: list[ResumeDefenseMatrixEntry] = Field(default_factory=list)


class ResumeDefenseRewriteEntry(BaseModel):
    claim_id: str
    question_id: str
    evidence_strength: str
    original_resume_claim: str
    related_job_requirement: str | None = None
    reason_for_weakness: str
    improved_resume_claim: str | None = None
    explanation_of_changes: str
    insufficient_evidence: bool = False


class ResumeDefenseRewriteSummary(BaseModel):
    targeted_claims: int = Field(ge=0)
    rewritten_claims: int = Field(ge=0)
    insufficient_evidence_claims: int = Field(ge=0)
    moderate_claims: int = Field(ge=0)
    weak_claims: int = Field(ge=0)


class ResumeDefenseRewriteResponse(BaseModel):
    session_id: str
    status: str
    generated_at: str
    summary: ResumeDefenseRewriteSummary
    entries: list[ResumeDefenseRewriteEntry] = Field(default_factory=list)


class ResumeDefenseReportingArtifact(BaseModel):
    detected_intent: str = "Resume_Defense_Report"
    result_text: str
    result_html: str
    narrative_summary: str


class ResumeDefenseCareerReadinessSummary(BaseModel):
    total_claims: int = Field(ge=0)
    strong_claims: int = Field(ge=0)
    moderate_claims: int = Field(ge=0)
    weak_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)
    well_defended_claims: int = Field(ge=0)
    challenged_claims: int = Field(ge=0)
    readiness_label: str
    rationale: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    preparation_priorities: list[str] = Field(default_factory=list)


class ResumeDefenseIntegratedReportResponse(BaseModel):
    session_id: str
    status: str
    generated_at: str
    narrative_summary: str
    career_readiness: ResumeDefenseCareerReadinessSummary
    matrix: ResumeDefenseMatrixResponse
    rewrites: ResumeDefenseRewriteResponse
    report: ResumeDefenseReportingArtifact


class ResumeDefenseStartRequest(BaseModel):
    resume_text: str = Field(..., min_length=80, max_length=30000)
    job_description: str = Field(default="", max_length=20000)
    analysis_output: str = Field(default="", max_length=30000)
    ats_missing_keywords: list[str] = Field(default_factory=list)
    ats_score: float | None = None
    model: str = ""


class ResumeDefenseAnswerSubmitRequest(BaseModel):
    question_id: str = Field(..., min_length=3, max_length=64)
    answer_text: str = Field(..., min_length=8, max_length=12000)


class ResumeDefenseSessionResponse(BaseModel):
    session_id: str
    status: str
    created_at: str
    updated_at: str
    resume_hash: str
    job_hash: str | None = None
    claims: list[ResumeDefenseClaim] = Field(default_factory=list)
    questions: list[ResumeDefenseQuestion] = Field(default_factory=list)
    evaluations: list[ResumeDefenseEvaluationResult] = Field(default_factory=list)
    signal_summary: ResumeDefenseSignalSummary
