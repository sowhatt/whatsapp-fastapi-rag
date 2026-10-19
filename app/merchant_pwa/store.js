// In-memory only. Never persist merchant data or credentials in browser storage.
export const state = {bootstrap: null, installPrompt: null};
export function clearState() { state.bootstrap = null; }
