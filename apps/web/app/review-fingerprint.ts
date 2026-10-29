/** Canonical JSON shared with the server; no cost or technical decisions. */
export function canonicalReview(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalReview).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalReview((value as Record<string, unknown>)[key])}`).join(",")}}`;
  }
  if (typeof value === "number" && !Number.isFinite(value)) throw new Error("Geçersiz sayısal önizleme.");
  const result = JSON.stringify(value);
  if (result === undefined) throw new Error("Geçersiz önizleme verisi.");
  return result;
}
export async function reviewFingerprint(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalReview(value));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}
