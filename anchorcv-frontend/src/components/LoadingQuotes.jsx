import { useEffect, useState } from "react";

export default function LoadingQuotes({ quotes, note }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % quotes.length);
    }, 3000);

    return () => window.clearInterval(timer);
  }, [quotes]);

  return (
    <div className="loading-quotes">
      <div className="loading-spinner" aria-hidden="true">
        *
      </div>
      <p className="loading-quote-copy">{quotes[index]}</p>
      <p className="loading-quote-note">{note}</p>
    </div>
  );
}
