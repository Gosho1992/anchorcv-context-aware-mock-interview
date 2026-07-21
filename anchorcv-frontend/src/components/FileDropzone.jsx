import { useRef, useState } from "react";

export default function FileDropzone({
  label,
  file,
  onChange,
  accept = ".pdf,.docx",
}) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef(null);

  const supportText =
    accept === ".pdf,.docx,.txt"
      ? "PDF, DOCX, and TXT supported"
      : "PDF and DOCX supported";

  function handleDragOver(event) {
    event.preventDefault();
    setIsDragOver(true);
  }

  function handleDragLeave(event) {
    if (!event.currentTarget.contains(event.relatedTarget)) {
      setIsDragOver(false);
    }
  }

  function handleDrop(event) {
    event.preventDefault();
    setIsDragOver(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) onChange(dropped);
  }

  function handleClick() {
    inputRef.current?.click();
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      inputRef.current?.click();
    }
  }

  return (
    <div
      className={`dropzone${isDragOver ? " dropzone-drag-over" : ""}`}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      role="button"
      tabIndex={0}
      aria-label={`${label} — drop a file or press Enter to browse`}
      style={{
        alignItems: "center",
        textAlign: "center",
        padding: "2rem 1.5rem",
        gap: "0.6rem",
        cursor: "pointer",
        userSelect: "none",
        borderStyle: "dashed",
        borderWidth: "1.5px",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: "none" }}
        onChange={(event) => onChange(event.target.files?.[0] || null)}
      />
      <span className="dropzone-icon" aria-hidden="true">
        {file ? "📄" : isDragOver ? "📥" : "📤"}
      </span>
      <strong className="dropzone-title" style={{ fontSize: "0.95rem" }}>
        {label}
      </strong>
      {file ? (
        <span className="dropzone-file-name">{file.name}</span>
      ) : (
        <span className="muted-copy" style={{ fontSize: "0.85rem" }}>
          {isDragOver ? "Drop to upload" : "Drag & drop or click to browse"}
        </span>
      )}
      <span className="subtle-copy" style={{ fontSize: "0.78rem" }}>
        {supportText}
      </span>
    </div>
  );
}
