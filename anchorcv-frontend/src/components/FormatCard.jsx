export default function FormatCard({ selected, title, description, badge, onClick }) {
  return (
    <button
      type="button"
      className={`format-card-v2${selected ? " selected" : ""}`}
      onClick={onClick}
      aria-pressed={selected}
    >
      {badge ? (
        <span className="format-card-badge">{badge}</span>
      ) : null}
      <span className="format-card-title">{title}</span>
      {description ? (
        <span className="format-card-desc">{description}</span>
      ) : null}
    </button>
  );
}
