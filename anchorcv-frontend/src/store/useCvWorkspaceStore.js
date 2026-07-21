import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export const defaultAnalysisOutputType = "Application_Strategy";
export const defaultBuilderFormat = "ATS-Optimized CV";
export const defaultBuilderSections = {
  summary: true,
  experience: true,
  education: true,
  skills: true,
  projects: true,
  publications: true,
  languages: true,
  certifications: true,
};

// localStorage with 7-day expiry so results survive tab closes
const EXPIRY_MS = 7 * 24 * 60 * 60 * 1000;

const storageWithExpiry = {
  getItem: (key) => {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed._expiry && Date.now() > parsed._expiry) {
        localStorage.removeItem(key);
        return null;
      }
      return JSON.stringify(parsed._state != null ? parsed._state : parsed);
    } catch {
      return null;
    }
  },
  setItem: (key, value) => {
    try {
      const wrapped = {
        _state: JSON.parse(value),
        _expiry: Date.now() + EXPIRY_MS,
      };
      localStorage.setItem(key, JSON.stringify(wrapped));
    } catch {
      // Storage full or unavailable
    }
  },
  removeItem: (key) => {
    try {
      localStorage.removeItem(key);
    } catch {}
  },
};

const initialState = {
  cvRequirementPrefill: "",
  analysisRequirementText: "",
  analysisOutputType: defaultAnalysisOutputType,
  analysisResult: null,
  analysisShowFullPreview: false,
  builderSelectedFormat: defaultBuilderFormat,
  builderTarget: "",
  builderGuidanceText: "",
  builderTone: "Professional",
  builderLanguage: "English",
  builderLength: "Full",
  builderColorTheme: "#7c6ff7",
  builderEnhance: true,
  builderSections: defaultBuilderSections,
  builderSpecialInstructions: "",
  builderResult: null,
  uploadedResumeFile: null,
  uploadedResumeFileName: "",
  discoveryQuery: "",
  discoveryLandscape: null,
  discoveryLoading: false,
  discoveryError: "",
  discoveryResumeText: "",
  discoveryResumeFilename: "",
};

const useCvWorkspaceStore = create(
  persist(
    (set) => ({
      ...initialState,
      setCvRequirementPrefill: (cvRequirementPrefill) => set({ cvRequirementPrefill }),
      clearCvRequirementPrefill: () => set({ cvRequirementPrefill: "" }),
      setAnalysisRequirementText: (analysisRequirementText) => set({ analysisRequirementText }),
      setAnalysisOutputType: (analysisOutputType) => set({ analysisOutputType }),
      setAnalysisResult: (analysisResult) => set({ analysisResult, analysisShowFullPreview: false }),
      setAnalysisShowFullPreview: (analysisShowFullPreview) => set({ analysisShowFullPreview }),
      clearAnalysis: () =>
        set({
          analysisRequirementText: "",
          analysisResult: null,
          analysisShowFullPreview: false,
          cvRequirementPrefill: "",
        }),
      setBuilderSelectedFormat: (builderSelectedFormat) => set({ builderSelectedFormat }),
      setBuilderTarget: (builderTarget) => set({ builderTarget }),
      setBuilderGuidanceText: (builderGuidanceText) => set({ builderGuidanceText }),
      setBuilderTone: (builderTone) => set({ builderTone }),
      setBuilderLanguage: (builderLanguage) => set({ builderLanguage }),
      setBuilderLength: (builderLength) => set({ builderLength }),
      setBuilderColorTheme: (builderColorTheme) => set({ builderColorTheme }),
      setBuilderEnhance: (builderEnhance) => set({ builderEnhance }),
      setBuilderSections: (builderSections) => set({ builderSections }),
      setBuilderSpecialInstructions: (builderSpecialInstructions) => set({ builderSpecialInstructions }),
      setBuilderResult: (builderResult) => set({ builderResult }),
      clearBuilder: () =>
        set({
          builderSelectedFormat: defaultBuilderFormat,
          builderTarget: "",
          builderGuidanceText: "",
          builderTone: "Professional",
          builderLanguage: "English",
          builderLength: "Full",
          builderColorTheme: "#7c6ff7",
          builderEnhance: true,
          builderSections: defaultBuilderSections,
          builderSpecialInstructions: "",
          builderResult: null,
        }),
      setUploadedResumeFile: (file) =>
        set({ uploadedResumeFile: file, uploadedResumeFileName: file?.name || "" }),
      clearUploadedResume: () =>
        set({ uploadedResumeFile: null, uploadedResumeFileName: "" }),
      setDiscoveryQuery: (discoveryQuery) => set({ discoveryQuery }),
      setDiscoveryLandscape: (discoveryLandscape) => set({ discoveryLandscape }),
      setDiscoveryLoading: (discoveryLoading) => set({ discoveryLoading }),
      setDiscoveryError: (discoveryError) => set({ discoveryError }),
      setDiscoveryResume: (discoveryResumeText, discoveryResumeFilename) =>
        set({
          discoveryResumeText: discoveryResumeText || "",
          discoveryResumeFilename: discoveryResumeFilename || "",
        }),
      clearDiscoveryResume: () =>
        set({ discoveryResumeText: "", discoveryResumeFilename: "" }),
      clearDiscovery: () =>
        set({
          discoveryQuery: "",
          discoveryLandscape: null,
          discoveryLoading: false,
          discoveryError: "",
          discoveryResumeText: "",
          discoveryResumeFilename: "",
        }),
    }),
    {
      name: "anchorcv-workspace",
      storage: createJSONStorage(() => storageWithExpiry),
      partialize: ({ uploadedResumeFile, discoveryLoading, ...rest }) => rest,
    }
  )
);

export default useCvWorkspaceStore;
