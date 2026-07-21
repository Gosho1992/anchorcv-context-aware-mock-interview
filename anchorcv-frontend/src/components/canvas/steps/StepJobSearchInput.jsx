import { useState } from "react";
import JobSearchFilters from "../../JobSearchFilters";
import StepWrapper from "../StepWrapper";
import { postJson } from "../../../api/client";
import useCanvasStore from "../../../store/useCanvasStore";

export default function StepJobSearchInput({ onComplete, onBack }) {
  const setJobResults = useCanvasStore((state) => state.setJobResults);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSearch(payload) {
    setLoading(true);
    setError("");
    try {
      const data = await postJson("/jobs/search", payload);
      setJobResults(data.jobs || [], {
        count: data.count ?? (data.jobs || []).length,
        query: data.query,
      });
      onComplete?.();
    } catch (err) {
      const msg = err?.detail || err?.message || "Job search failed.";
      setError(typeof msg === "string" ? msg : "Job search failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <StepWrapper
      title="Search live jobs"
      description="Find live roles, then turn any of them into a tailored application."
      onBack={onBack}
    >
      <JobSearchFilters
        onSearch={handleSearch}
        loading={loading}
        error={error}
        showExamples
      />
    </StepWrapper>
  );
}
