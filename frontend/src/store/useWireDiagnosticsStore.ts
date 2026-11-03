import { create } from 'zustand';

export interface WireDiagnostic {
  endpoint: 'start' | 'end';
  pin: string;
  message: string;
}
export const useWireDiagnosticsStore = create<{
  errors: Record<string, WireDiagnostic>;
  set: (wire: string, value: WireDiagnostic) => void;
  clear: () => void;
}>((set) => ({
  errors: {},
  set: (wire, value) => set((state) => ({ errors: { ...state.errors, [wire]: value } })),
  clear: () => set({ errors: {} }),
}));
