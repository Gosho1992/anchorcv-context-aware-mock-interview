import { useEffect, useState } from "react";
import { getJson } from "../api/client";

// Module-level cache: the model list only changes when server keys change.
let cachedResponse = null;

export default function ModelSelect({ value, onChange, disabled = false, compact = false }) {
  const [models, setModels] = useState(cachedResponse?.models || []);
  const [defaultModel, setDefaultModel] = useState(cachedResponse?.default || "");

  useEffect(() => {
    let isActive = true;

    async function loadModels() {
      if (cachedResponse) {
        return;
      }
      try {
        const response = await getJson("/models");
        if (!response || !Array.isArray(response.models)) {
          return;
        }
        cachedResponse = response;
        if (isActive) {
          setModels(response.models);
          setDefaultModel(response.default || "");
        }
      } catch {
        // Model picker is optional — backend default is used when hidden.
      }
    }

    loadModels();
    return () => {
      isActive = false;
    };
  }, []);

  // Hide entirely when only one (or zero) models are available.
  if (models.length < 2) {
    return null;
  }

  const selected = value || defaultModel || models[0]?.id || "";

  return (
    <label className="stack tight" style={{ maxWidth: compact ? "260px" : "340px" }}>
      <span className="eyebrow">AI Model</span>
      <select
        className="input-modern"
        value={selected}
        onChange={(event) => onChange?.(event.target.value)}
        disabled={disabled}
        aria-label="Choose AI model"
      >
        {models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.label}
            {model.tier === "advanced" ? " · advanced" : ""}
          </option>
        ))}
      </select>
      {!compact ? (
        <span className="subtle-copy" style={{ fontSize: "0.78rem" }}>
          {models.find((model) => model.id === selected)?.description || ""}
        </span>
      ) : null}
    </label>
  );
}
