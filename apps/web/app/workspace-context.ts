/** Navigation hints only. All referenced records must be revalidated by the API. */
export const WORKSPACE_KEY = "arkemx.workspace.v1";
type Workspace = { version: 1; owner: string; projectId: string; importId: string | null };

function ownerOf(token: string): string | null {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(payload));
    return typeof claims.sub === "string" && claims.sub ? claims.sub : null;
  } catch { return null; }
}
export function clearWorkspace(storage: Storage = sessionStorage): void {
  try { storage.removeItem(WORKSPACE_KEY); } catch { /* Storage can be disabled. */ }
}
export function readWorkspace(token: string, storage: Storage = sessionStorage): Workspace | null {
  try {
    const owner = ownerOf(token);
    const value = JSON.parse(storage.getItem(WORKSPACE_KEY) ?? "null");
    if (!owner || !value || value.version !== 1 || value.owner !== owner ||
      typeof value.projectId !== "string" || !value.projectId ||
      !(value.importId === null || typeof value.importId === "string")) return null;
    return value;
  } catch { return null; }
}
export function rememberProject(token: string, projectId: string, storage: Storage = sessionStorage): void {
  const owner = ownerOf(token);
  if (!owner || !projectId) { clearWorkspace(storage); return; }
  const previous = readWorkspace(token, storage);
  try { storage.setItem(WORKSPACE_KEY, JSON.stringify({ version: 1, owner, projectId,
    importId: previous?.projectId === projectId ? previous.importId : null })); } catch { /* Navigation still works. */ }
}
export function rememberImport(token: string, projectId: string, importId: string | null, storage: Storage = sessionStorage): void {
  rememberProject(token, projectId, storage);
  const value = readWorkspace(token, storage);
  if (!value) return;
  try { storage.setItem(WORKSPACE_KEY, JSON.stringify({ ...value, importId })); } catch { /* Navigation still works. */ }
}
