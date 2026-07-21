import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import CanvasFlow from "./components/canvas/CanvasFlow";
import CanvasLayout from "./components/canvas/CanvasLayout";
import AccountPage from "./pages/AccountPage";
import AnalysisPage from "./pages/AnalysisPage";
import ATSPage from "./pages/ATSPage";
import BuilderPage from "./pages/BuilderPage";
import CanvasTestPage from "./pages/CanvasTestPage";
import DashboardPage from "./pages/DashboardPage";
import DiscoveryPage from "./pages/DiscoveryPage";
import FilesPage from "./pages/FilesPage";
import FirstResumePage from "./pages/FirstResumePage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import JobsPage from "./pages/JobsPage";
import LoginPage from "./pages/LoginPage";
import PaymentPage from "./pages/PaymentPage";
import PaymentSuccessPage from "./pages/PaymentSuccessPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import TemplatesPage from "./pages/TemplatesPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route element={<ProtectedRoute requirePremium={false} />}>
        <Route path="/payment" element={<PaymentPage />} />
        <Route path="/payment-success" element={<PaymentSuccessPage />} />
      </Route>
      <Route element={<ProtectedRoute requirePremium={false} />}>
        <Route element={<CanvasLayout />}>
          <Route path="/canvas" element={<CanvasFlow />} />
        </Route>
      </Route>
      <Route path="/" element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/canvas" replace />} />
          <Route path="dashboard-legacy" element={<DashboardPage />} />
          <Route path="first-resume" element={<FirstResumePage />} />
          <Route path="discover" element={<DiscoveryPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="analysis" element={<AnalysisPage />} />
          <Route path="canvas-test" element={<CanvasTestPage />} />
          <Route path="ats-shield" element={<ATSPage />} />
          <Route path="builder" element={<BuilderPage />} />
          <Route path="templates" element={<TemplatesPage />} />
          <Route path="files" element={<FilesPage />} />
          <Route path="account" element={<AccountPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
