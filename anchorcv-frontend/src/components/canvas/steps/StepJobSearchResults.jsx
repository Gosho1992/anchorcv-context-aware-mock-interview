import { useState } from "react";
import JobResultsList from "../../JobResultsList";
import StepWrapper from "../StepWrapper";
import { postJson } from "../../../api/client";
import useCanvasStore from "../../../store/useCanvasStore";

// Compose the JD text sent to match + generation from a job card.
function jobToJd(job) {
  return [
    job.title,
    job.company ? `Company: ${job.company}` : "",
    job.location ? `Location: ${job.location}` : "",
    job.salary ? `Salary: ${job.salary}` : "",
    "",
    job.snippet || "",
  ]
    .filter((line) => line !== undefined && line !== null)
    .join("\n")
    .trim();
}

export default function StepJobSearchResults({ onBack, onFinish }) {
  const jobResults = useCanvasStore((state) => state.jobResults);
  const jobSearchMeta = useCanvasStore((state) => state.jobSearchMeta);
  const uploadedCV = useCanvasStore((state) => state.uploadedCV);
  const cvText = useCanvasStore((state) => state.cvText);
  const setJD = useCanvasStore((state) => state.setJD);
  const setFlow = useCanvasStore((state) => state.setFlow);
  const setStep = useCanvasStore((state) => state.setStep);
  const setSelectedOutputs = useCanvasStore((state) => state.setSelectedOutputs);

  const [matches, setMatches] = useState({});
  const [error, setError] = useState("");

  const hasCv = Boolean(uploadedCV || (cvText || "").trim());

  async function handleMatch(job, idx) {
    if (!(cvText || "").trim()) {
      setError("Add a CV in a CV flow first to see match scores.");
      return;
    }
    setMatches((prev) => ({ ...prev, [idx]: { loading: true } }));
    try {
      const data = await postJson("/jobs/match-score", {
        cv_text: cvText,
        job_title: job.title || "",
        company_name: job.company || "",
        job_description: jobToJd(job),
      });
      setMatches((prev) => ({
        ...prev,
        [idx]: { loading: false, score: data.overall_score, detail: data },
      }));
    } catch (err) {
      const msg = err?.detail || err?.message || "Could not score this job.";
      setMatches((prev) => ({
        ...prev,
        [idx]: { loading: false, error: typeof msg === "string" ? msg : "Could not score this job." },
      }));
    }
  }

  // Turn a job card into a tailored application: pre-fill the JD from the job,
  // switch to the 'job' flow, and jump straight to Select Outputs when a CV
  // already exists (skip Upload + Paste JD since both are already satisfied).
  function goToJobFlow(job, output) {
    setJD(jobToJd(job));
    setSelectedOutputs([output]);
    setFlow("job"); // resets currentStep to 0 and loads the job flow's steps
    // job flow = [upload, paste, outputs, generate, results, export]
    // outputs is index 2 => step number 3; upload is step number 1
    setStep(hasCv ? 3 : 1);
  }

  return (
    <StepWrapper
      title="Live jobs"
      description="Score any role against your CV, or turn it into a tailored application."
      onBack={onBack}
      maxWidth="100%"
    >
      <div className="stack">
        {jobSearchMeta ? (
          <div className="analysis-meta-card">
            <p style={{ margin: 0 }}>
              <strong>{jobSearchMeta.count}</strong>{" "}
              {jobSearchMeta.count === 1 ? "result" : "results"}
              {jobSearchMeta.query ? <> for "{jobSearchMeta.query}"</> : null}
            </p>
          </div>
        ) : null}

        {error ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{error}</p>
          </div>
        ) : null}

        <JobResultsList
          jobs={jobResults}
          matches={matches}
          hasCv={hasCv}
          onMatch={handleMatch}
          onCover={(job) => goToJobFlow(job, "Cover_Letter")}
          onTailorResume={(job) => goToJobFlow(job, "Resume_Optimization")}
        />

        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button type="button" className="secondary-button" onClick={onFinish}>
            Done
          </button>
        </div>
      </div>
    </StepWrapper>
  );
}
