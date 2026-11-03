import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

// Step sequences per flow. The step list is FROZEN at setFlow() time so that
// mid-step state changes (e.g. uploading a CV sets cvText) can never re-index
// the sequence and skip steps.
export const FLOW_STEPS = {
  job: ["upload", "paste", "outputs", "generate", "results", "export"],
  scholarship: ["upload", "paste", "outputs", "generate", "results", "export"],
  discovery: ["discoveryInput", "discoveryLandscape"],
  buildCV: ["upload", "buildCV"],
  improveResume: ["upload", "paste", "outputs", "generate", "results", "export"],
  atsCheck: ["upload", "paste", "atsResults", "export"],
  jobSearch: ["jobSearchInput", "jobSearchResults"],
  templates: ["upload", "templateSelect", "templateResults", "export"],
  interview: ["upload", "interviewSetup", "interviewSession", "interviewReport"],
};

const initialState = {
  currentFlow: null,
  currentStep: 0,
  flowSteps: [],
  uploadedCV: null,
  cvFileName: "",
  cvText: "",
  jdText: "",
  selectedOutputs: [],
  selectedModel: "",
  generatedResults: {},
  discoveryData: null,
  jobResults: null,
  jobSearchMeta: null,
  templateSelection: null,
  templateConvertResult: null,
  templateCompareResult: null,
  interviewConfig: null,
  interviewQuestions: [],
  interviewAnswers: {},
  interviewReport: null,
  interviewCompanyBrief: null,
  interviewOtariCalls: [],
  contextEvidenceSessionId: "",
  contextEvidenceClaims: [],
  contextEvidenceQuestions: [],
  contextEvidenceAnswers: {},
  contextEvidenceEvaluations: {},
  interviewEvidence: null,
  interviewEvidenceRewrites: null,
  isProcessing: false,
  error: null,
  cvReplaceOpen: false,
};

const useCanvasStore = create(
  persist(
    (set) => ({
      ...initialState,
      setFlow(flow) {
        // The step list is frozen at flow start. The upload step is ALWAYS
        // included - when a CV already exists, StepUploadCV renders a
        // ready-state with Replace/Continue instead of being skipped, so the
        // user can always swap their CV.
        const flowSteps = [...(FLOW_STEPS[flow] || [])];
        set({ currentFlow: flow, currentStep: 0, flowSteps, error: null });
      },
      nextStep() {
        set((state) => ({ currentStep: state.currentStep + 1 }));
      },
      setStep(step) {
        const safeStep = Number.isFinite(step) ? Math.max(0, Math.floor(step)) : 0;
        set({ currentStep: safeStep });
      },
      prevStep() {
        set((state) => ({ currentStep: Math.max(0, state.currentStep - 1) }));
      },
      setUploadedCV(file, text = "") {
        set({
          uploadedCV: file || null,
          cvFileName: file?.name || "",
          cvText: text || "",
        });
      },
      setJD(text) {
        set({ jdText: text || "" });
      },
      toggleOutput(outputType) {
        set((state) => ({
          selectedOutputs: state.selectedOutputs.includes(outputType)
            ? state.selectedOutputs.filter((item) => item !== outputType)
            : [...state.selectedOutputs, outputType],
        }));
      },
      setSelectedOutputs(outputs) {
        set({ selectedOutputs: Array.isArray(outputs) ? outputs : [] });
      },
      setSelectedModel(model) {
        set({ selectedModel: model || "" });
      },
      setGeneratedResults(results) {
        set({ generatedResults: results || {} });
      },
      setDiscoveryData(data) {
        set({ discoveryData: data || null });
      },
      setJobResults(results, meta) {
        set({
          jobResults: Array.isArray(results) ? results : null,
          jobSearchMeta: meta || null,
        });
      },
      setTemplateSelection(selection) {
        set({ templateSelection: selection || null });
      },
      setTemplateConvertResult(result) {
        set({ templateConvertResult: result || null });
      },
      setTemplateCompareResult(result) {
        set({ templateCompareResult: result || null });
      },
      setIsProcessing(isProcessing) {
        set({ isProcessing: Boolean(isProcessing) });
      },
      setError(error) {
        set({ error: error || null });
      },
      clearError() {
        set({ error: null });
      },
      setInterviewConfig(config) {
        set({ interviewConfig: config || null });
      },
      setInterviewQuestions(questions) {
        // New question set starts a fresh session.
        set({
          interviewQuestions: Array.isArray(questions) ? questions : [],
          interviewAnswers: {},
          interviewReport: null,
        });
      },
      setInterviewAnswer(questionId, answer) {
        set((state) => ({
          interviewAnswers: { ...state.interviewAnswers, [questionId]: answer },
        }));
      },
      setInterviewReport(report) {
        set({ interviewReport: report || null });
      },
      setInterviewCompanyBrief(brief) {
        set({ interviewCompanyBrief: brief || null });
      },
      // Each interview API response carries what Otari reported (model that
      // served it, fallback, cost, guardrail); collected for the report.
      addInterviewOtariCalls(otari) {
        const calls = Array.isArray(otari?.calls) ? otari.calls : [];
        if (!calls.length) {
          return;
        }
        set((state) => ({
          interviewOtariCalls: [...state.interviewOtariCalls, ...calls].slice(-200),
        }));
      },
      clearInterviewOtariCalls() {
        set({ interviewOtariCalls: [] });
      },
      setContextEvidenceSession(session) {
        const questions = Array.isArray(session?.questions) ? session.questions : [];
        const claims = Array.isArray(session?.claims) ? session.claims : [];
        const evaluations = Array.isArray(session?.evaluations) ? session.evaluations : [];

        const evaluationMap = evaluations.reduce((acc, item) => {
          if (item?.question_id) {
            acc[item.question_id] = item;
          }
          return acc;
        }, {});

        const answerMap = evaluations.reduce((acc, item) => {
          if (item?.question_id && item?.answer_excerpt) {
            acc[item.question_id] = item.answer_excerpt;
          }
          return acc;
        }, {});

        set({
          contextEvidenceSessionId: session?.session_id || "",
          contextEvidenceClaims: claims,
          contextEvidenceQuestions: questions,
          contextEvidenceAnswers: answerMap,
          contextEvidenceEvaluations: evaluationMap,
          interviewEvidence: null,
          interviewEvidenceRewrites: null,
        });
      },
      setContextEvidenceAnswer(questionId, answerText) {
        if (!questionId) {
          return;
        }
        set((state) => ({
          contextEvidenceAnswers: {
            ...state.contextEvidenceAnswers,
            [questionId]: answerText || "",
          },
        }));
      },
      setContextEvidenceEvaluation(evaluation) {
        const questionId = evaluation?.question_id;
        if (!questionId) {
          return;
        }
        set((state) => ({
          contextEvidenceEvaluations: {
            ...state.contextEvidenceEvaluations,
            [questionId]: evaluation,
          },
        }));
      },
      setInterviewEvidence(matrix) {
        set({ interviewEvidence: matrix || null });
      },
      setInterviewEvidenceRewrites(rewrites) {
        set({ interviewEvidenceRewrites: rewrites || null });
      },
      clearContextEvidence() {
        set({
          contextEvidenceSessionId: "",
          contextEvidenceClaims: [],
          contextEvidenceQuestions: [],
          contextEvidenceAnswers: {},
          contextEvidenceEvaluations: {},
          interviewEvidence: null,
          interviewEvidenceRewrites: null,
        });
      },
      openCvReplace() {
        set({ cvReplaceOpen: true });
      },
      closeCvReplace() {
        set({ cvReplaceOpen: false });
      },
      reset() {
        set({ ...initialState });
      },
    }),
    {
      name: "anchorcv-canvas",
      storage: createJSONStorage(() => localStorage),
      // Persist everything serializable so a refresh mid-flow resumes where
      // the user left off. uploadedCV is a File object and cannot be
      // persisted - StepGenerate falls back to building a text file from
      // cvText when the File is missing.
      partialize: (state) => ({
        currentFlow: state.currentFlow,
        currentStep: state.currentStep,
        flowSteps: state.flowSteps,
        cvFileName: state.cvFileName,
        cvText: state.cvText,
        jdText: state.jdText,
        selectedOutputs: state.selectedOutputs,
        selectedModel: state.selectedModel,
        generatedResults: state.generatedResults,
        discoveryData: state.discoveryData,
        jobResults: state.jobResults,
        jobSearchMeta: state.jobSearchMeta,
        templateSelection: state.templateSelection,
        templateConvertResult: state.templateConvertResult,
        templateCompareResult: state.templateCompareResult,
        interviewConfig: state.interviewConfig,
        interviewQuestions: state.interviewQuestions,
        interviewAnswers: state.interviewAnswers,
        interviewReport: state.interviewReport,
        interviewCompanyBrief: state.interviewCompanyBrief,
        interviewOtariCalls: state.interviewOtariCalls,
        contextEvidenceSessionId: state.contextEvidenceSessionId,
        contextEvidenceClaims: state.contextEvidenceClaims,
        contextEvidenceQuestions: state.contextEvidenceQuestions,
        contextEvidenceAnswers: state.contextEvidenceAnswers,
        contextEvidenceEvaluations: state.contextEvidenceEvaluations,
        interviewEvidence: state.interviewEvidence,
        interviewEvidenceRewrites: state.interviewEvidenceRewrites,
      }),
    }
  )
);

export default useCanvasStore;



