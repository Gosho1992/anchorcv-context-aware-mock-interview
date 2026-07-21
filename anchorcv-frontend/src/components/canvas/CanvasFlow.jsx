import { useEffect, useRef } from "react";
import StepIntent from "./steps/StepIntent";
import StepBuildCV from "./steps/StepBuildCV";
import StepDiscoveryInput from "./steps/StepDiscoveryInput";
import StepDiscoveryLandscape from "./steps/StepDiscoveryLandscape";
import StepExport from "./steps/StepExport";
import StepGenerate from "./steps/StepGenerate";
import StepPasteJD from "./steps/StepPasteJD";
import StepResults from "./steps/StepResults";
import StepSelectOutputs from "./steps/StepSelectOutputs";
import StepUploadCV from "./steps/StepUploadCV";
import StepATSResults from "./steps/StepATSResults";
import StepJobSearchInput from "./steps/StepJobSearchInput";
import StepJobSearchResults from "./steps/StepJobSearchResults";
import StepTemplateSelect from "./steps/StepTemplateSelect";
import StepTemplateResults from "./steps/StepTemplateResults";
import StepInterviewSetup from "./steps/StepInterviewSetup";
import StepInterviewSession from "./steps/StepInterviewSession";
import StepInterviewReport from "./steps/StepInterviewReport";
import useCanvasStore from "../../store/useCanvasStore";
import { beaconCanvasEvent, trackCanvasEvent } from "../../utils/canvasAnalytics";

export default function CanvasFlow() {
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const currentStep = useCanvasStore((state) => state.currentStep);
  const resolvedSteps = useCanvasStore((state) => state.flowSteps);
  const cvReplaceOpen = useCanvasStore((state) => state.cvReplaceOpen);
  const closeCvReplace = useCanvasStore((state) => state.closeCvReplace);
  const generatedResults = useCanvasStore((state) => state.generatedResults);
  const nextStep = useCanvasStore((state) => state.nextStep);
  const prevStep = useCanvasStore((state) => state.prevStep);
  const setStep = useCanvasStore((state) => state.setStep);
  const setFlow = useCanvasStore((state) => state.setFlow);
  const reset = useCanvasStore((state) => state.reset);
  const flowStartRef = useRef(null);
  const startedFlowRef = useRef(null);
  const activeStepRef = useRef(null);
  const flowCompletedRef = useRef(false);

  const stepIndex = currentStep - 1;
  const currentKey = stepIndex >= 0 ? resolvedSteps[stepIndex] : null;
  const hasActiveFlow = Boolean(currentFlow) && currentStep > 0 && Boolean(currentKey);

  function finishFlow() {
    const active = activeStepRef.current;
    if (active) {
      trackCanvasEvent("canvas_step_completed", {
        flow: active.flow,
        step_name: active.stepKey,
        step_index: active.stepIndex,
        time_on_step_seconds: Math.max(0, Math.round((Date.now() - active.startedAt) / 1000)),
      });
    }

    if (currentFlow) {
      const totalMs = flowStartRef.current ? Date.now() - flowStartRef.current : 0;
      trackCanvasEvent("canvas_flow_completed", {
        flow: currentFlow,
        total_time_seconds: Math.max(0, Math.round(totalMs / 1000)),
        outputs_generated: Object.keys(generatedResults || {}).length,
      });
    }
    flowCompletedRef.current = true;
    activeStepRef.current = null;
    flowStartRef.current = null;
    startedFlowRef.current = null;
    reset();
  }

  useEffect(() => {
    if (!hasActiveFlow) {
      return;
    }

    if (startedFlowRef.current !== currentFlow) {
      startedFlowRef.current = currentFlow;
      flowStartRef.current = Date.now();
      flowCompletedRef.current = false;
      activeStepRef.current = null;
      trackCanvasEvent("canvas_flow_started", {
        flow: currentFlow,
        timestamp: new Date().toISOString(),
      });
    }

    const now = Date.now();
    const previous = activeStepRef.current;
    if (!previous) {
      activeStepRef.current = {
        flow: currentFlow,
        stepIndex,
        stepKey: currentKey,
        startedAt: now,
      };
      return;
    }

    const stepChanged =
      previous.flow !== currentFlow ||
      previous.stepIndex !== stepIndex ||
      previous.stepKey !== currentKey;
    if (!stepChanged) {
      return;
    }

    const movedForward = previous.flow === currentFlow && stepIndex > previous.stepIndex;
    const switchedFlow = previous.flow !== currentFlow;
    if (movedForward || switchedFlow) {
      trackCanvasEvent("canvas_step_completed", {
        flow: previous.flow,
        step_name: previous.stepKey,
        step_index: previous.stepIndex,
        time_on_step_seconds: Math.max(0, Math.round((now - previous.startedAt) / 1000)),
      });
    }

    activeStepRef.current = {
      flow: currentFlow,
      stepIndex,
      stepKey: currentKey,
      startedAt: now,
    };
  }, [currentFlow, currentStep, currentKey, hasActiveFlow, stepIndex]);

  useEffect(() => {
    function reportAbandon() {
      const active = activeStepRef.current;
      if (!active || flowCompletedRef.current) {
        return;
      }
      beaconCanvasEvent("canvas_step_abandoned", {
        flow: active.flow,
        step_name: active.stepKey,
        step_index: active.stepIndex,
      });
      activeStepRef.current = null;
    }

    window.addEventListener("beforeunload", reportAbandon);
    return () => {
      window.removeEventListener("beforeunload", reportAbandon);
      reportAbandon();
    };
  }, []);

  // Standalone CV replacement (opened from the top bar or dashboard) —
  // renders regardless of flow state and returns the user where they were.
  if (cvReplaceOpen) {
    return (
      <StepUploadCV standalone onComplete={closeCvReplace} onBack={closeCvReplace} />
    );
  }

  if (!currentFlow || currentStep === 0) {
    return <StepIntent />;
  }

  if (stepIndex >= resolvedSteps.length) {
    return (
      <section className="page-container page-enter">
        <div className="panel stack">
          <p className="eyebrow">Canvas</p>
          <h2 className="page-title">Flow Complete</h2>
          <p className="muted-copy" style={{ margin: 0 }}>
            You have completed the {currentFlow} flow.
          </p>
          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button
              type="button"
              className="primary-button"
              onClick={finishFlow}
            >
              Finish
            </button>
          </div>
        </div>
      </section>
    );
  }

  function goToStep(stepKey) {
    const index = resolvedSteps.indexOf(stepKey);
    if (index >= 0) {
      setStep(index + 1);
    }
  }

  if (currentKey === "upload") {
    return <StepUploadCV onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "paste") {
    return <StepPasteJD onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "outputs") {
    return <StepSelectOutputs onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "generate") {
    return <StepGenerate onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "results") {
    return (
      <StepResults
        onBack={prevStep}
        onEditJD={() => goToStep("paste")}
        onEditOutputs={() => goToStep("outputs")}
        onComplete={nextStep}
      />
    );
  }
  if (currentKey === "export") {
    return <StepExport onBack={prevStep} onRestart={finishFlow} />;
  }
  if (currentKey === "atsResults") {
    return <StepATSResults onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "jobSearchInput") {
    return <StepJobSearchInput onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "jobSearchResults") {
    return <StepJobSearchResults onBack={prevStep} onFinish={finishFlow} />;
  }
  if (currentKey === "templateSelect") {
    return <StepTemplateSelect onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "templateResults") {
    return <StepTemplateResults onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "interviewSetup") {
    return <StepInterviewSetup onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "interviewSession") {
    return <StepInterviewSession onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "interviewReport") {
    return <StepInterviewReport onBack={prevStep} onRestart={finishFlow} />;
  }

  if (currentKey === "discoveryInput") {
    return <StepDiscoveryInput onComplete={nextStep} onBack={prevStep} />;
  }
  if (currentKey === "discoveryLandscape") {
    return (
      <StepDiscoveryLandscape
        onBack={prevStep}
        onFinish={finishFlow}
        onSwitchFlow={(flow) => {
          setFlow(flow);
          nextStep();
        }}
      />
    );
  }
  if (currentKey === "buildCV") {
    return <StepBuildCV onBack={prevStep} onComplete={nextStep} />;
  }

  return (
    <section className="page-container page-enter">
      <div className="panel">
        <p className="eyebrow">Canvas Flow</p>
        <h2 className="page-title">Unknown Step</h2>
        <p className="muted-copy" style={{ margin: 0 }}>
          Selected flow: <strong>{currentFlow}</strong>. Step key not recognized.
        </p>
      </div>
    </section>
  );
}



