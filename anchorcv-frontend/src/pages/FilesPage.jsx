import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  deleteFile,
  getFileDownloadUrl,
  listFiles,
  uploadFile,
} from "../api/client";
import useAuthStore from "../store/useAuthStore";

function triggerDownload(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.target = "_blank";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function viewHtmlFile(url) {
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) throw new Error("Failed to fetch file.");
  const text = await response.text();
  const blob = new Blob([text], { type: "text/html" });
  const objectUrl = URL.createObjectURL(blob);
  window.open(objectUrl, "_blank");
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

function viewStoredFile(url, filename) {
  const normalized = String(filename || "").toLowerCase();
  if (normalized.endsWith(".html")) {
    return viewHtmlFile(url);
  }
  if (normalized.endsWith(".pdf")) {
    window.open(url, "_blank");
    return Promise.resolve();
  }
  window.open(url, "_blank");
  return Promise.resolve();
}

function formatFileDate(value) {
  if (!value) {
    return "Unknown date";
  }

  try {
    return new Date(value).toLocaleDateString();
  } catch (error) {
    return value;
  }
}

function getFileBadge(filename) {
  const normalized = String(filename || "").toLowerCase();

  if (normalized.endsWith(".pdf")) {
    return { label: "PDF", className: "pdf" };
  }

  if (normalized.endsWith(".docx")) {
    return { label: "DOCX", className: "docx" };
  }

  if (normalized.endsWith(".html")) {
    return { label: "HTML", className: "html" };
  }

  return null;
}

export default function FilesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const hydrateAuth = useAuthStore((state) => state.hydrate);
  const [file, setFile] = useState(null);
  const [inputKey, setInputKey] = useState(0);

  useEffect(() => {
    document.title = "Files · AnchorCV";
  }, []);

  const filesQuery = useQuery({
    queryKey: ["files"],
    queryFn: listFiles,
  });

  const uploadMutation = useMutation({
    mutationFn: async (fileToUpload) => {
      const formData = new FormData();
      formData.append("file", fileToUpload);
      return uploadFile(formData);
    },
    onSuccess: async () => {
      setFile(null);
      setInputKey((k) => k + 1);
      toast.success("File uploaded.");
      await queryClient.invalidateQueries({ queryKey: ["files"] });
      await hydrateAuth();
    },
    onError: (error) => {
      toast.error(error.message || "Upload failed.");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteFile,
    onSuccess: async () => {
      toast.success("File deleted.");
      await queryClient.invalidateQueries({ queryKey: ["files"] });
      await hydrateAuth();
    },
    onError: (error) => {
      toast.error(error.message || "Delete failed.");
    },
  });

  return (
    <section className="stack page-enter">
      <div className="panel stack">
        <div>
          <p className="eyebrow">Files</p>
          <h2 className="page-title">My Files</h2>
          <p className="muted-copy">
            View, download, and manage the documents you have generated in
            AnchorCV.
          </p>
        </div>

        <div className="button-row files-upload-row">
          <input
            key={inputKey}
            type="file"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
          <button
            className="primary-button"
            disabled={!file || uploadMutation.isPending}
            onClick={() => uploadMutation.mutate(file)}
          >
            {uploadMutation.isPending ? "Uploading..." : "Upload file"}
          </button>
        </div>

        {uploadMutation.error ? (
          <p className="error-text">{uploadMutation.error.message}</p>
        ) : null}
      </div>

      <div className="panel stack">
        {filesQuery.isLoading ? (
          <p className="muted-copy">Loading files...</p>
        ) : null}

        {filesQuery.data?.files?.map((storedFile) => {
          const badge = getFileBadge(storedFile.filename);

          return (
            <div key={storedFile.id} className="file-row">
              <div className="stack tight">
                <div className="file-meta">
                  <strong>{storedFile.filename}</strong>
                  {badge ? (
                    <span className={`file-badge ${badge.className}`}>
                      {badge.label}
                    </span>
                  ) : null}
                </div>
                <p className="muted-copy">
                  {Math.round((storedFile.size_bytes || 0) / 1024)} KB &middot;{" "}
                  {formatFileDate(storedFile.created_at)}
                </p>
              </div>

              <div
                className="button-row"
                style={{ justifyContent: "flex-end", flexWrap: "wrap" }}
              >
                <button
                  className="secondary-button"
                  onClick={() => {
                    viewStoredFile(
                      getFileDownloadUrl(storedFile.id),
                      storedFile.filename
                    ).catch((err) => {
                      toast.error(err.message || "Unable to open file.");
                    });
                  }}
                >
                  View
                </button>

                <button
                  className="secondary-button"
                  onClick={() =>
                    triggerDownload(
                      getFileDownloadUrl(storedFile.id),
                      storedFile.filename
                    )
                  }
                >
                  Download
                </button>

                <button
                  className="secondary-button"
                  disabled={deleteMutation.isPending}
                  onClick={() => {
                    const confirmed = window.confirm(
                      `Delete ${storedFile.filename}? This cannot be undone.`
                    );
                    if (!confirmed) {
                      return;
                    }
                    deleteMutation.mutate(storedFile.id);
                  }}
                >
                  Delete
                </button>
              </div>
            </div>
          );
        })}

        {!filesQuery.data?.files?.length && !filesQuery.isLoading ? (
          <div className="empty-state stack">
            <p className="eyebrow">Nothing here yet</p>
            <h3 className="page-title" style={{ margin: 0 }}>
              No files yet
            </h3>
            <p className="muted-copy" style={{ margin: 0 }}>
              Generate your first CV or run an analysis to see your documents
              here.
            </p>
            <div>
              <button
                className="primary-button"
                onClick={() => navigate("/analysis")}
              >
                Go to Analysis →
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
