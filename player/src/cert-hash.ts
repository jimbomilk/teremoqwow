/** Fetches cert hash from KrakenD /cert-hash, falling back to a provided getter. */
export async function fetchCertHash(
  getCertHashAttr: () => string | null,
): Promise<string | null> {
  try {
    const r = await fetch('/cert-hash');
    if (r.ok) {
      const d = await r.json();
      if (d.cert_hash) return d.cert_hash;
    }
  } catch (_) {}
  return getCertHashAttr() || null;
}
