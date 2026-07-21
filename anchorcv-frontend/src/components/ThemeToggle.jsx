import { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [isLight, setIsLight] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("anchorcv-theme");
      if (saved === "light") {
        setIsLight(true);
        document.documentElement.setAttribute("data-theme", "light");
      }
    } catch {
      // localStorage unavailable — stay dark
    }
  }, []);

  function toggle() {
    const next = !isLight;
    setIsLight(next);
    if (next) {
      document.documentElement.setAttribute("data-theme", "light");
      try { localStorage.setItem("anchorcv-theme", "light"); } catch {}
    } else {
      document.documentElement.removeAttribute("data-theme");
      try { localStorage.setItem("anchorcv-theme", "dark"); } catch {}
    }
  }

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      title={isLight ? "Switch to dark mode" : "Switch to light mode"}
    >
      <span>{isLight ? "🌙" : "☀️"}</span>
      <span>{isLight ? "Dark" : "Light"}</span>
    </button>
  );
}
