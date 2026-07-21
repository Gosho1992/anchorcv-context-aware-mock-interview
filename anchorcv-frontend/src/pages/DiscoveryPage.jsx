import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { postJson, postMultipart } from "../api/client";
import DiscoveryInputControls, { REGION_OPTIONS } from "../components/DiscoveryInputControls";
import DiscoveryLandscape from "../components/DiscoveryLandscape";
import useAuthStore from "../store/useAuthStore";
import useCvWorkspaceStore from "../store/useCvWorkspaceStore";

const SAMPLE_LANDSCAPE = {
  primary_field: "Electrical Engineering",
  intent: "phd",
  related_subfields: [
    {
      name: "Power Electronics & Smart Grids",
      description: "Research into high-efficiency converters, grid-tied inverters, and smart energy distribution networks.",
      growing: true,
      hot_regions: ["Germany", "Netherlands", "Denmark"],
      typical_roles: ["Postdoctoral Researcher", "R&D Scientist", "Academic Faculty"],
      distance_from_user: "close",
      why: "Active funded positions at TU Delft, KIT, and DTU â€” strong alignment with power systems background.",
    },
    {
      name: "Electromagnetic Compatibility & Antenna Design",
      description: "Doctoral research on EM interference, antenna arrays, and RF system design for communications and radar.",
      growing: true,
      hot_regions: ["Germany", "Sweden", "Japan"],
      typical_roles: ["Research Scientist", "RF Engineer (R&D)", "Postdoc"],
      distance_from_user: "close",
      why: "JSPS and DAAD both fund EMC-related doctoral work; strong demand from defence and automotive sectors.",
    },
    {
      name: "Control Systems & Autonomous Systems",
      description: "PhD research on advanced control theory, robotics, and autonomous vehicle dynamics.",
      growing: true,
      hot_regions: ["Netherlands", "Switzerland", "Canada"],
      typical_roles: ["Postdoctoral Researcher", "Control Systems Researcher", "Faculty Lecturer"],
      distance_from_user: "4-8 weeks",
      why: "ETH Zurich and TU Delft have funded PhD positions; overlap with ME and robotics opens wider funding pools.",
    },
    {
      name: "Nanoelectronics & Semiconductor Devices",
      description: "Research into next-generation semiconductor fabrication, quantum devices, and nano-scale transistors.",
      growing: true,
      hot_regions: ["Netherlands", "USA", "Japan"],
      typical_roles: ["Postdoctoral Researcher", "Device Physicist", "Materials Scientist"],
      distance_from_user: "3-6 months",
      why: "IMEC (Belgium) and ASML (Netherlands) co-fund PhDs; highly competitive but well-resourced.",
    },
    {
      name: "Signal Processing for Communications",
      description: "Doctoral work on 5G/6G signal design, channel estimation, and digital communications algorithms.",
      growing: true,
      hot_regions: ["Sweden", "Finland", "Germany"],
      typical_roles: ["Research Engineer", "Postdoc", "DSP Scientist"],
      distance_from_user: "4-8 weeks",
      why: "Ericsson, Nokia, and Huawei all co-fund PhDs in Nordic universities.",
    },
  ],
  adjacent_fields: [
    {
      name: "Computational Electromagnetics",
      description: "Numerical simulation of EM fields â€” bridges EE with applied mathematics and physics.",
      growing: true,
      distance_from_user: "4-8 weeks",
      why: "Strong overlap with antenna and power electronics research; opens physics faculty positions.",
    },
    {
      name: "Energy Systems Engineering",
      description: "Cross-disciplinary PhD work on grid integration of renewables and energy storage.",
      growing: true,
      distance_from_user: "3-6 months",
      why: "Many funded positions under EU Green Deal initiatives; combines EE with policy and economics.",
    },
  ],
  known_opportunities: [
    {
      title: "DAAD Research Grant â€“ PhD in Electrical Engineering",
      institution: "DAAD",
      country: "Germany",
      type: "PhD",
      note: "Covers tuition, stipend (~â‚¬1,200/mo), and travel. For all EE research areas. Verify on official site.",
    },
    {
      title: "Marie SkÅ‚odowska-Curie Doctoral Networks",
      institution: "Marie SkÅ‚odowska-Curie Actions",
      country: "EU (multi-country)",
      type: "PhD",
      note: "Fully funded 3-year positions across European universities. Competitive but well-resourced. Verify on official site.",
    },
    {
      title: "NSERC Postgraduate Scholarship â€“ Doctoral",
      institution: "NSERC",
      country: "Canada",
      type: "PhD",
      note: "CAD $21kâ€“$35k/yr for Canadian university PhD programmes in natural sciences and engineering. Verify on official site.",
    },
  ],
  search_tags: [
    "funded PhD electrical engineering Germany 2026",
    "doctoral researcher power electronics TU Delft",
    "DAAD PhD grant electrical engineering application",
    "Marie Curie doctoral network EE 2026",
    "PhD position smart grid Netherlands",
    "funded PhD control systems ETH Zurich",
    "doctoral researcher signal processing Sweden Nokia",
    "JSPS fellowship electrical engineering Japan",
    "PhD semiconductor devices IMEC Belgium",
    "EPSRC doctoral training partnership electrical engineering UK",
  ],
  summary:
    "Electrical Engineering is one of the best-funded PhD fields in Europe right now. Power electronics, control systems, and signal processing all have active funded positions â€” particularly in Germany, the Netherlands, and Scandinavia. DAAD and Marie SkÅ‚odowska-Curie Actions are the strongest starting points. Upload your CV to see how your specific background maps onto these research areas.",
  gap_analysis: null,
  regional_demand: [
    { region: "Germany", demand_level: "high", trending: true, typical_salary: "â‚¬1,800â€“â‚¬2,400/mo stipend", notes: "Largest funded EE PhD ecosystem in Europe; DAAD, DFG, and industry co-funded positions widely available." },
    { region: "Netherlands", demand_level: "high", trending: true, typical_salary: "â‚¬2,200â€“â‚¬2,800/mo", notes: "TU Delft and Eindhoven University offer funded positions with full employee status." },
    { region: "Sweden", demand_level: "medium", trending: true, typical_salary: "SEK 28kâ€“34k/mo", notes: "Industry PhDs with Ericsson and ABB very common; treated as employment." },
    { region: "Canada", demand_level: "medium", trending: false, typical_salary: "CAD $21kâ€“$35k/yr", notes: "NSERC funding widely available; strong in power and control systems." },
  ],
  learning_paths: [
    {
      title: "Prepare a competitive PhD application",
      steps: [
        "Identify 5â€“8 potential supervisors whose research overlaps yours â€” email them directly",
        "Update your academic CV to highlight thesis work, publications, and technical projects",
        "Write a 1-page research proposal tailored to each group's active projects",
        "Apply to DAAD Research Grant and Marie Curie Doctoral Networks before their deadlines",
        "Ask two professors for strong reference letters focused on research potential",
      ],
      duration: "8â€“12 weeks",
      outcome: "A targeted application package positioned for funded PhD positions in top European EE groups.",
    },
  ],
  salary_insights: "Funded EE PhD positions in the Netherlands pay ~â‚¬2,200â€“â‚¬2,800/month as a full employee. German positions via DAAD pay ~â‚¬1,800â€“â‚¬2,400/month. Swedish industry PhDs with Ericsson or ABB pay SEK 28kâ€“34k/month. Most positions include health insurance and social contributions.",
  cached: false,
  __sample: true,
};

const DISCOVERY_USAGE_KEY = "anchorcv_discovery_uses_today";

export default function DiscoveryPage() {
  const navigate = useNavigate();
  const setAnalysisRequirementText = useCvWorkspaceStore((s) => s.setAnalysisRequirementText);
  const hydrateAuth = useAuthStore((s) => s.hydrate);
  const user = useAuthStore((s) => s.user);
  const accessStatus = useAuthStore((s) => s.accessStatus);

  const query = useCvWorkspaceStore((s) => s.discoveryQuery);
  const setQuery = useCvWorkspaceStore((s) => s.setDiscoveryQuery);
  const landscape = useCvWorkspaceStore((s) => s.discoveryLandscape);
  const setLandscape = useCvWorkspaceStore((s) => s.setDiscoveryLandscape);
  const loading = useCvWorkspaceStore((s) => s.discoveryLoading);
  const setLoading = useCvWorkspaceStore((s) => s.setDiscoveryLoading);
  const error = useCvWorkspaceStore((s) => s.discoveryError);
  const setError = useCvWorkspaceStore((s) => s.setDiscoveryError);
  const resumeText = useCvWorkspaceStore((s) => s.discoveryResumeText);
  const resumeFilename = useCvWorkspaceStore((s) => s.discoveryResumeFilename);
  const setResume = useCvWorkspaceStore((s) => s.setDiscoveryResume);
  const clearResume = useCvWorkspaceStore((s) => s.clearDiscoveryResume);

  const [intent, setIntent] = useState("job");
  const [region, setRegion] = useState("anywhere");
  const [resumeUploading, setResumeUploading] = useState(false);
  const [usageCount, setUsageCount] = useState(0);
  const fileInputRef = useRef(null);

  const isFirstTimeUser = !user?.onboarded_at;
  const showSample = isFirstTimeUser && !landscape && !loading;
  const displayedLandscape = showSample ? SAMPLE_LANDSCAPE : landscape;
  const isSample = displayedLandscape?.__sample === true;
  const isPremium = accessStatus?.access === "premium";
  const isBlocked = accessStatus?.access === "blocked";

  // Intent labels â€” derived from the landscape's own intent field so cached results
  // always render with the correct labels, not whatever the selector currently shows.`r`n
  useEffect(() => {
    document.title = "Discover Â· AnchorCV";
    const stored = Number(sessionStorage.getItem(DISCOVERY_USAGE_KEY) || 0);
    setUsageCount(Number.isFinite(stored) ? stored : 0);
  }, []);

  const quotaLabel = useMemo(
    () => (isPremium ? "Unlimited" : `${usageCount} / 20 daily uses`),
    [isPremium, usageCount]
  );

  async function handleExplore(bypassCache = false) {
    if (isBlocked) return;

    const trimmed = (query || "").trim();
    if (!trimmed) return;

    const regionLabel =
      region === "anywhere"
        ? "worldwide"
        : REGION_OPTIONS.find((o) => o.value === region)?.label?.replace(/^[^\s]+\s/, "") || region;

    const fullQuery = `${trimmed} | region: ${regionLabel}`;

    setLoading(true);
    setError("");

    try {
      const data = await postJson("/discover/landscape", {
        query: fullQuery,
        intent,
        bypass_cache: bypassCache,
        resume_text: resumeText || undefined,
      });

      setLandscape(data);

      if (!isPremium) {
        const next = usageCount + 1;
        setUsageCount(next);
        sessionStorage.setItem(DISCOVERY_USAGE_KEY, String(next));
      }

      if (!useAuthStore.getState().user?.onboarded_at) {
        postJson("/auth/me/onboard", {}).then(() => hydrateAuth()).catch(() => {});
      }
    } catch (err) {
      const msg = err?.detail || err?.message || "Something went wrong.";
      setError(typeof msg === "string" ? msg : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleResumeFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setResumeUploading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await postMultipart("/discover/extract-resume", formData);
      setResume(response.resume_text, response.filename);
    } catch (err) {
      const msg = err?.detail || err?.message || "Could not read the file.";
      setError(typeof msg === "string" ? msg : "Could not read the file.");
    } finally {
      setResumeUploading(false);
    }
  }

  function handleAnalyzeOpportunity(opp) {
    const req = [opp.title, `${opp.institution}, ${opp.country}`, `Type: ${opp.type}`, opp.note]
      .filter(Boolean).join("\n");
    setAnalysisRequirementText(req);
    navigate("/analysis");
  }

  function handleUseSearchTag(tag) {
    window.open(`https://www.google.com/search?q=${encodeURIComponent(tag)}`, "_blank", "noopener,noreferrer");
  }

  function handleCopyAllTags() {
    if (displayedLandscape?.search_tags?.length) {
      navigator.clipboard.writeText(displayedLandscape.search_tags.join("\n"));
    }
  }

  return (
    <section className="stack page-enter" style={{ gap: "1.75rem" }}>
                  <DiscoveryInputControls
        query={query}
        setQuery={setQuery}
        intent={intent}
        setIntent={setIntent}
        region={region}
        setRegion={setRegion}
        loading={loading}
        landscape={landscape}
        error={error}
        isBlocked={isBlocked}
        quotaLabel={quotaLabel}
        resumeUploading={resumeUploading}
        resumeFilename={resumeFilename}
        resumeText={resumeText}
        fileInputRef={fileInputRef}
        onExplore={handleExplore}
        onUpgrade={() => navigate('/payment')}
        onResumeFile={handleResumeFile}
        onClearResume={clearResume}
      />

      {/* Sample banner â”€â”€ */}
      {isSample && (
        <div className="panel" style={{ background: "rgba(99,102,241,0.10)", border: "1px solid rgba(99,102,241,0.4)" }}>
          <strong style={{ color: "#c7d2fe" }}>This is a sample landscape.</strong>
          <p className="muted-copy" style={{ margin: "0.4rem 0 0" }}>
            Type your background, interests, or target programmes above and click Explore to see a personalised version.
          </p>
        </div>
      )}

            {displayedLandscape && (
        <>
          <DiscoveryLandscape
            displayedLandscape={displayedLandscape}
            isSample={isSample}
            loading={loading}
            onRegenerate={() => handleExplore(true)}
            onAnalyzeOpportunity={handleAnalyzeOpportunity}
            onUseSearchTag={handleUseSearchTag}
            onCopyAllTags={handleCopyAllTags}
          />

          <div className="discover-footer-row">
            <span className="muted-copy">Missing a scholarship or program in this landscape?</span>
            <a className="secondary-button compact-button" href="mailto:hello@anchorcv.com?subject=Suggest%20a%20program">
              Suggest a program
            </a>
          </div>
        </>
      )}
    </section>
  );
}


