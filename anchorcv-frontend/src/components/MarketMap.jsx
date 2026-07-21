import { useCallback, useEffect, useRef, useState } from "react";

function buildNodes(landscape, dimensions) {
  if (!landscape) return [];
  const nodes = [];
  const cx = dimensions.width / 2;
  const cy = dimensions.height / 2;

  nodes.push({
    id: "center",
    label: landscape.primary_field || "You",
    sublabel: "Your position",
    x: cx,
    y: cy,
    radius: 30,
    color: "#7c6ff7",
    glowColor: "rgba(124,111,247,0.45)",
    type: "center",
    growing: true,
  });

  const related = landscape.related_subfields || [];
  related.forEach((field, i) => {
    const angle = (i / related.length) * Math.PI * 2 - Math.PI / 2;
    const dist = 155 + (i % 2 === 0 ? -18 : 18);
    nodes.push({
      id: `rel-${i}`,
      label: field.name,
      sublabel: field.distance_from_user,
      x: cx + Math.cos(angle) * dist,
      y: cy + Math.sin(angle) * dist * 0.72,
      radius: field.growing ? 21 : 16,
      color: field.growing ? "#2dd4a8" : "#f5a623",
      glowColor: field.growing
        ? "rgba(45,212,168,0.38)"
        : "rgba(245,166,35,0.32)",
      type: "related",
      growing: field.growing,
      data: field,
    });
  });

  const adjacent = landscape.adjacent_fields || [];
  adjacent.forEach((field, i) => {
    const angle =
      (i / Math.max(adjacent.length, 1)) * Math.PI * 2 + Math.PI / 5;
    const dist = 270 + (i % 2 === 0 ? -20 : 20);
    nodes.push({
      id: `adj-${i}`,
      label: field.name,
      sublabel: field.distance_from_user,
      x: cx + Math.cos(angle) * dist,
      y: cy + Math.sin(angle) * dist * 0.65,
      radius: 12,
      color: "#6b6b63",
      glowColor: "rgba(148,163,184,0.18)",
      type: "adjacent",
      growing: field.growing,
      data: field,
    });
  });

  return nodes;
}

function initParticles(w, h) {
  return Array.from({ length: 50 }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    size: Math.random() * 1.6 + 0.4,
    vx: (Math.random() - 0.5) * 0.28,
    vy: (Math.random() - 0.5) * 0.28,
    opacity: Math.random() * 0.35 + 0.08,
  }));
}

export default function MarketMap({ landscape, onNodeClick }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const rafRef = useRef(null);
  const particlesRef = useRef([]);
  const timeRef = useRef(0);
  const [dims, setDims] = useState({ width: 760, height: 480 });
  const [hovered, setHovered] = useState(null);
  const [selected, setSelected] = useState(null);

  // Responsive sizing
  useEffect(() => {
    function update() {
      if (!containerRef.current) return;
      const w = containerRef.current.getBoundingClientRect().width || 760;
      const h = Math.max(420, Math.round(w * 0.6));
      setDims({ width: Math.round(w), height: h });
    }
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // Re-init particles when dims change
  useEffect(() => {
    particlesRef.current = initParticles(dims.width, dims.height);
  }, [dims]);

  const nodes = buildNodes(landscape, dims);

  // Main draw loop
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const { width: W, height: H } = dims;
    const cx = W / 2;
    const cy = H / 2;
    timeRef.current += 0.006;
    const t = timeRef.current;

    ctx.clearRect(0, 0, W, H);

    // Ambient particles
    particlesRef.current.forEach((p) => {
      p.x = (p.x + p.vx + W) % W;
      p.y = (p.y + p.vy + H) % H;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(124,111,247,${p.opacity})`;
      ctx.fill();
    });

    // Orbit rings
    [155, 270].forEach((r, ri) => {
      ctx.beginPath();
      ctx.ellipse(cx, cy, r, r * (ri === 0 ? 0.72 : 0.65), 0, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,255,255,0.04)";
      ctx.lineWidth = 1;
      ctx.stroke();
    });

    // Connection lines
    nodes
      .filter((n) => n.type !== "center")
      .forEach((node) => {
        const alpha =
          0.12 - Math.hypot(node.x - cx, node.y - cy) / (W * 3);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(node.x, node.y);
        ctx.strokeStyle = `rgba(124,111,247,${Math.max(0.03, alpha)})`;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 7]);
        ctx.stroke();
        ctx.setLineDash([]);
      });

    // Nodes — draw adjacent first, then related, then center
    const order = ["adjacent", "related", "center"];
    [...nodes]
      .sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type))
      .forEach((node) => {
        const isHov = hovered?.id === node.id;
        const isSel = selected?.id === node.id;
        const scale = isHov ? 1.22 : isSel ? 1.15 : 1;
        const baseR = node.radius * scale;
        const pulseR =
          node.growing && node.type !== "center"
            ? baseR + Math.sin(t * 2.8 + node.x * 0.05) * 2.2
            : baseR;

        // Outer glow
        if (node.type !== "adjacent" || isHov || isSel) {
          const glow = ctx.createRadialGradient(
            node.x,
            node.y,
            pulseR * 0.3,
            node.x,
            node.y,
            pulseR * 2.8
          );
          glow.addColorStop(0, node.glowColor);
          glow.addColorStop(1, "transparent");
          ctx.beginPath();
          ctx.arc(node.x, node.y, pulseR * 2.8, 0, Math.PI * 2);
          ctx.fillStyle = glow;
          ctx.fill();
        }

        // Main circle
        const grad = ctx.createRadialGradient(
          node.x - pulseR * 0.28,
          node.y - pulseR * 0.28,
          pulseR * 0.1,
          node.x,
          node.y,
          pulseR
        );
        if (node.type === "center") {
          grad.addColorStop(0, "#a99cf8");
          grad.addColorStop(0.65, "#7c6ff7");
          grad.addColorStop(1, "rgba(124,111,247,0.25)");
        } else {
          grad.addColorStop(0, node.color);
          grad.addColorStop(1, node.color + "30");
        }
        ctx.beginPath();
        ctx.arc(node.x, node.y, pulseR, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.strokeStyle = isHov || isSel
          ? "rgba(255,255,255,0.55)"
          : "rgba(255,255,255,0.15)";
        ctx.lineWidth = isHov || isSel ? 2 : 1;
        ctx.stroke();

        // Center dashed ring
        if (node.type === "center") {
          ctx.beginPath();
          ctx.arc(node.x, node.y, pulseR + 7, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(124,111,247,0.28)";
          ctx.lineWidth = 1.5;
          ctx.setLineDash([6, 5]);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // Labels
        const showLabel =
          node.type === "center" ||
          node.type === "related" ||
          isHov ||
          isSel;
        if (showLabel) {
          const lx = node.x;
          const ly = node.y + pulseR + 15;
          ctx.textAlign = "center";
          ctx.font = node.type === "center"
            ? "bold 11px Inter, system-ui, sans-serif"
            : "10px Inter, system-ui, sans-serif";
          ctx.fillStyle = node.type === "center" ? "#f0efe9" : "#d0cfc9";

          // Wrap long names
          const words = node.label.split(" ");
          const lines = [];
          let cur = "";
          words.forEach((w) => {
            const test = cur ? `${cur} ${w}` : w;
            if (test.length > 16 && cur) {
              lines.push(cur);
              cur = w;
            } else {
              cur = test;
            }
          });
          if (cur) lines.push(cur);

          lines.forEach((line, li) => ctx.fillText(line, lx, ly + li * 13));

          if (node.sublabel) {
            ctx.font = "9px Inter, system-ui, sans-serif";
            ctx.fillStyle = "#6b6b63";
            ctx.fillText(
              node.sublabel,
              lx,
              ly + lines.length * 13 + 3
            );
          }
        }
      });

    // Legend
    ctx.font = "9px Inter, system-ui, sans-serif";
    ctx.fillStyle = "rgba(152,152,143,0.7)";
    ctx.textAlign = "center";
    ctx.fillText(
      "● Teal = Growing fast  ● Amber = Stable  ○ Grey = Adjacent  — click any node",
      cx,
      H - 14
    );

    rafRef.current = requestAnimationFrame(draw);
  }, [nodes, hovered, selected, dims]);

  useEffect(() => {
    rafRef.current = requestAnimationFrame(draw);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [draw]);

  // Pointer tracking
  const getNode = useCallback(
    (e) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return null;
      const scaleX = dims.width / rect.width;
      const scaleY = dims.height / rect.height;
      const mx = (e.clientX - rect.left) * scaleX;
      const my = (e.clientY - rect.top) * scaleY;
      return (
        nodes.find(
          (n) => Math.hypot(mx - n.x, my - n.y) < n.radius * 1.6
        ) || null
      );
    },
    [nodes, dims]
  );

  const handleMouseMove = useCallback(
    (e) => {
      const n = getNode(e);
      setHovered(n);
      if (canvasRef.current)
        canvasRef.current.style.cursor = n && n.type !== "center"
          ? "pointer"
          : "default";
    },
    [getNode]
  );

  const handleClick = useCallback(
    (e) => {
      const n = getNode(e);
      if (n && n.type !== "center") {
        setSelected((prev) => (prev?.id === n.id ? null : n));
        onNodeClick?.(n);
      }
    },
    [getNode, onNodeClick]
  );

  const handleMouseLeave = () => setHovered(null);

  return (
    <div ref={containerRef} style={{ position: "relative", width: "100%" }}>
      <canvas
        ref={canvasRef}
        width={dims.width}
        height={dims.height}
        onMouseMove={handleMouseMove}
        onClick={handleClick}
        onMouseLeave={handleMouseLeave}
        style={{
          width: "100%",
          height: "auto",
          display: "block",
          borderRadius: "var(--radius-lg)",
          background: "rgba(14,14,18,0.65)",
          border: "1px solid var(--border)",
        }}
      />

      {/* Hover tooltip */}
      {hovered && hovered.type !== "center" && (
        <div
          style={{
            position: "absolute",
            top: (hovered.y / dims.height) * 100 + "%",
            left: (hovered.x / dims.width) * 100 + "%",
            transform: "translate(-50%, calc(-100% - 14px))",
            background: "var(--bg-raised)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--radius-md)",
            padding: "0.65rem 0.9rem",
            pointerEvents: "none",
            zIndex: 10,
            boxShadow: "var(--shadow-elevated)",
            minWidth: "160px",
            maxWidth: "220px",
            textAlign: "center",
          }}
        >
          <p
            style={{
              fontWeight: 700,
              fontSize: "0.88rem",
              color: "var(--text-primary)",
              margin: "0 0 0.2rem",
            }}
          >
            {hovered.label}
          </p>
          <p
            style={{
              fontSize: "0.76rem",
              color: "var(--text-muted)",
              margin: "0 0 0.4rem",
            }}
          >
            {hovered.sublabel} ·{" "}
            {hovered.growing ? "↑ Growing" : "→ Stable"}
          </p>
          {hovered.data?.hot_regions?.length > 0 && (
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "0.25rem",
                justifyContent: "center",
              }}
            >
              {hovered.data.hot_regions.slice(0, 3).map((r) => (
                <span
                  key={r}
                  style={{
                    fontSize: "0.7rem",
                    padding: "0.1rem 0.45rem",
                    borderRadius: "999px",
                    background: "rgba(255,255,255,0.06)",
                    border: "1px solid var(--border)",
                    color: "var(--text-secondary)",
                  }}
                >
                  {r}
                </span>
              ))}
            </div>
          )}
          <p
            style={{
              fontSize: "0.7rem",
              color: "var(--accent-soft)",
              margin: "0.4rem 0 0",
            }}
          >
            Click to explore →
          </p>
        </div>
      )}

      {/* Click-expand detail panel */}
      {selected && selected.type !== "center" && selected.data && (
        <div
          className="glass-panel"
          style={{
            marginTop: "1rem",
            padding: "1.25rem 1.5rem",
            animation: "card-enter 0.3s cubic-bezier(0.16,1,0.3,1) both",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              gap: "1rem",
              flexWrap: "wrap",
            }}
          >
            <div style={{ flex: 1 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.75rem",
                  marginBottom: "0.5rem",
                }}
              >
                <h3 style={{ margin: 0 }}>{selected.label}</h3>
                <span
                  className={`badge ${
                    selected.growing ? "badge-teal" : "badge-warning"
                  }`}
                >
                  {selected.growing ? "↑ Growing" : "→ Stable"}
                </span>
              </div>
              <p
                className="muted-copy"
                style={{ margin: 0, fontSize: "0.92rem" }}
              >
                {selected.data.description}
              </p>
            </div>
            <button
              onClick={() => setSelected(null)}
              style={{
                background: "none",
                border: "1px solid var(--border)",
                borderRadius: "999px",
                color: "var(--text-muted)",
                padding: "0.2rem 0.7rem",
                fontSize: "0.8rem",
                cursor: "pointer",
                minHeight: "auto",
              }}
            >
              ✕
            </button>
          </div>

          <div
            style={{
              display: "flex",
              gap: "2rem",
              marginTop: "1rem",
              flexWrap: "wrap",
            }}
          >
            {selected.sublabel && (
              <div>
                <p className="eyebrow" style={{ marginBottom: "0.2rem" }}>
                  Distance
                </p>
                <p style={{ fontWeight: 600, margin: 0, fontSize: "0.9rem" }}>
                  {selected.sublabel}
                </p>
              </div>
            )}
            {selected.data.hot_regions?.length > 0 && (
              <div>
                <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>
                  Hot regions
                </p>
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "0.3rem",
                  }}
                >
                  {selected.data.hot_regions.map((r) => (
                    <span
                      key={r}
                      style={{
                        fontSize: "0.8rem",
                        padding: "0.2rem 0.6rem",
                        borderRadius: "999px",
                        background: "rgba(124,111,247,0.1)",
                        border: "1px solid rgba(124,111,247,0.25)",
                        color: "var(--accent-soft)",
                      }}
                    >
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {selected.data.why && (
            <p
              style={{
                marginTop: "0.8rem",
                fontSize: "0.85rem",
                color: "var(--text-muted)",
                fontStyle: "italic",
              }}
            >
              {selected.data.why}
            </p>
          )}

          <div
            style={{
              display: "flex",
              gap: "0.75rem",
              marginTop: "1.1rem",
              flexWrap: "wrap",
            }}
          >
            <button
              className="primary-button-glow"
              style={{ padding: "0.55rem 1.3rem", fontSize: "0.88rem" }}
              onClick={() => {
                const q = selected.label + " opportunities";
                window.open(
                  `https://www.google.com/search?q=${encodeURIComponent(q)}`,
                  "_blank",
                  "noopener,noreferrer"
                );
              }}
            >
              🔍 Search opportunities
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
