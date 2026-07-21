import { create } from "zustand";
import { getCurrentUser, login as loginRequest, logout as logoutRequest, register as registerRequest } from "../api/client";

const useAuthStore = create((set) => ({
  user: null,
  accessStatus: null,
  status: "idle",
  error: null,
  setUser(user, accessStatus = null) {
    set({
      user,
      accessStatus,
      status: user ? "authenticated" : "anonymous",
      error: null
    });
  },
  async hydrate() {
    set({ status: "loading", error: null });
    try {
      const response = await getCurrentUser();
      set({ user: response.user, accessStatus: response.access_status || null, status: "authenticated" });
    } catch (error) {
      set({ user: null, accessStatus: null, status: "anonymous", error: null });
    }
  },
  async login(payload) {
    set({ status: "loading", error: null });
    try {
      const response = await loginRequest(payload);
      set({ user: response.user, accessStatus: response.access_status || null, status: "authenticated" });
      return { user: response.user, accessStatus: response.access_status || null };
    } catch (error) {
      set({ error: error.message, status: "anonymous" });
      throw error;
    }
  },
  async register(payload) {
    set({ status: "loading", error: null });
    try {
      const response = await registerRequest(payload);
      set({ user: response.user, accessStatus: response.access_status || null, status: "authenticated" });
      return { user: response.user, accessStatus: response.access_status || null };
    } catch (error) {
      set({ error: error.message, status: "anonymous" });
      throw error;
    }
  },
  async logout() {
    await logoutRequest();
    set({ user: null, accessStatus: null, status: "anonymous", error: null });
  }
}));

export default useAuthStore;
