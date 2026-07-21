import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import useAuthStore from "../store/useAuthStore";

export default function ProtectedRoute({ requirePremium = true }) {
  const location = useLocation();
  const { status, user, hydrate } = useAuthStore();

  useEffect(() => {
    if (status === "idle") {
      hydrate();
    }
  }, [hydrate, status]);

  if (status === "idle" || status === "loading") {
    return <div className="screen-shell"><div className="panel">Loading AnchorCV...</div></div>;
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
