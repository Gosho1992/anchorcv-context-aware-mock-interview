import { postJson } from "../api/client";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export async function trackCanvasEvent(eventName, payload = {}) {
  try {
    await postJson("/analytics/canvas-event", {
      event_name: eventName,
      timestamp: new Date().toISOString(),
      payload,
    });
  } catch {
    // Analytics should never block the UI flow.
  }
}

export function beaconCanvasEvent(eventName, payload = {}) {
  try {
    if (typeof navigator === "undefined" || typeof navigator.sendBeacon !== "function") {
      return;
    }

    const body = JSON.stringify({
      event_name: eventName,
      timestamp: new Date().toISOString(),
      payload,
    });
    const blob = new Blob([body], { type: "application/json" });
    navigator.sendBeacon(`${API_BASE}/analytics/canvas-event`, blob);
  } catch {
    // Analytics should never block the UI flow.
  }
}
