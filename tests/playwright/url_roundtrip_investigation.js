/**
 * URL state round-trip investigation (issue #201, Part 2).
 *
 * Hypothesis space (from #201):
 *   1. Copy mid-debounce → URL stale
 *   2. heading=360 normalized to 0 → param dropped
 *   3. Cold-cache point-mode latency → "different view" = "samples not loaded yet"
 *   4. 5000-cap with no ORDER BY → different 5000 across browsers
 *   5. _suppressHashWrite stuck via rapid hashchanges
 *
 * Method:
 *   - Context A loads the Cyprus deep-link, settles into point mode,
 *     then performs N deterministic flyTo() pan/zoom steps. After each
 *     settle, snapshots the URL + viewer state + cachedData length.
 *   - For each snapshot, Context B opens a fresh page at that URL,
 *     waits stable, snapshots the same fields. Compares.
 *
 * Output:
 *   - /tmp/url_roundtrip_log.json — full structured log
 *   - stdout summary of diffs
 */

const { chromium } = require('playwright');

const SITE = process.env.TEST_URL || 'https://isamples.org/explorer.html';
const START_HASH = '#v=1&lat=34.9957&lng=33.6798&alt=15212&heading=360.0&mode=point';
const ITERATIONS = 6;
const SETTLE_MS = 2500;          // after a camera move, wait for debounce + URL write
const B_WAITS = [5000, 15000, 30000];  // probe Context B at multiple times

/**
 * Capture all the state we care about from a page that has booted the explorer.
 * Returns null if the explorer isn't ready yet.
 */
async function capture(page, label) {
  return await page.evaluate(async (label) => {
    const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer').catch(() => null);
    if (!v || !v.camera || !v._globeState) return { label, ready: false, url: location.href };
    const carto = v.camera.positionCartographic;
    const cached = await window._ojs.ojsConnector.mainModule.value('cachedData').catch(() => null);
    return {
      label,
      ready: true,
      ts: Date.now(),
      url: location.href,
      hash: location.hash,
      camera: {
        lat: Cesium.Math.toDegrees(carto.latitude),
        lng: Cesium.Math.toDegrees(carto.longitude),
        alt: carto.height,
        heading: Cesium.Math.toDegrees(v.camera.heading),
        pitch: Cesium.Math.toDegrees(v.camera.pitch),
      },
      mode: v._globeState.mode,
      selectedPid: v._globeState.selectedPid || null,
      selectedH3: v._globeState.selectedH3 || null,
      cachedDataLen: Array.isArray(cached) ? cached.length : null,
      suppressHashWrite: !!v._suppressHashWrite,
      selGen: v._selGen || null,
      phaseMsg: document.getElementById('phaseMsg')?.textContent?.trim() || '',
      sSamples: document.getElementById('sSamples')?.textContent?.trim() || '',
    };
  }, label);
}

/**
 * Wait until viewer is initialized and we're in point mode (deep-link end state).
 */
async function waitReadyAndPointMode(page, timeoutMs = 120000) {
  return page.waitForFunction(
    async () => {
      try {
        const v = await window._ojs?.ojsConnector?.mainModule?.value('viewer');
        if (!v?._globeState) return false;
        return v._globeState.mode === 'point';
      } catch { return false; }
    },
    null,
    { timeout: timeoutMs }
  );
}

/**
 * Drive the camera with a deterministic flyTo, return after a settle period.
 */
async function flyAndSettle(page, target, settleMs = SETTLE_MS) {
  await page.evaluate(async ({ lat, lng, alt, heading, pitch, durationS }) => {
    const v = await window._ojs.ojsConnector.mainModule.value('viewer');
    v.camera.cancelFlight();
    v.scene.requestRenderMode = false;
    v.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lng, lat, alt),
      orientation: {
        heading: Cesium.Math.toRadians(heading),
        pitch: Cesium.Math.toRadians(pitch),
      },
      duration: durationS,
    });
  }, target);
  // Wait flight duration + debounce + a margin
  await page.waitForTimeout((target.durationS * 1000) + settleMs);
}

/** Diff two captures, return human-readable list of significant deltas. */
function diff(a, b) {
  const out = [];
  if (!a?.ready || !b?.ready) {
    out.push(`ready: A=${a?.ready} B=${b?.ready}`);
    return out;
  }
  const dLat = Math.abs(a.camera.lat - b.camera.lat);
  const dLng = Math.abs(a.camera.lng - b.camera.lng);
  const dAlt = Math.abs(a.camera.alt - b.camera.alt);
  const dHeading = Math.min(
    Math.abs(a.camera.heading - b.camera.heading),
    360 - Math.abs(a.camera.heading - b.camera.heading)
  );
  const dPitch = Math.abs(a.camera.pitch - b.camera.pitch);
  if (dLat > 0.001) out.push(`lat Δ${dLat.toFixed(5)}`);
  if (dLng > 0.001) out.push(`lng Δ${dLng.toFixed(5)}`);
  if (dAlt > 50) out.push(`alt Δ${Math.round(dAlt)}m (A=${Math.round(a.camera.alt)} B=${Math.round(b.camera.alt)})`);
  if (dHeading > 1) out.push(`heading Δ${dHeading.toFixed(1)}° (A=${a.camera.heading.toFixed(1)} B=${b.camera.heading.toFixed(1)})`);
  if (dPitch > 1) out.push(`pitch Δ${dPitch.toFixed(1)}°`);
  if (a.mode !== b.mode) out.push(`mode A=${a.mode} B=${b.mode}`);
  if (a.cachedDataLen !== b.cachedDataLen) out.push(`cachedDataLen A=${a.cachedDataLen} B=${b.cachedDataLen}`);
  return out;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctxA = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const pageA = await ctxA.newPage();

  console.log('=== Context A: load Cyprus deep-link ===');
  await pageA.goto(SITE + START_HASH, { waitUntil: 'domcontentloaded' });
  console.log('  waiting for point mode (cold-cache can take 60-90s)...');
  await waitReadyAndPointMode(pageA);
  // Extra settle so sample fetch completes
  await pageA.waitForTimeout(3000);
  const initialA = await capture(pageA, 'A-initial');
  console.log('  ready. initial URL:', initialA.url);
  console.log('  mode=', initialA.mode, ' alt=', Math.round(initialA.camera.alt), ' cachedData=', initialA.cachedDataLen, ' sSamples=', initialA.sSamples);

  // Define a series of pan/zoom targets. Mix of pure-pan, zoom-only, heading change,
  // and a small move that should NOT cross the point/cluster boundary.
  const targets = [
    { lat: 34.9957, lng: 33.6798, alt: 15212, heading: 0,   pitch: -90, durationS: 1.2, note: 'pure pan: heading 0' },
    { lat: 35.0150, lng: 33.7000, alt: 15212, heading: 0,   pitch: -90, durationS: 1.2, note: 'pan NE' },
    { lat: 35.0150, lng: 33.7000, alt:  8000, heading: 0,   pitch: -90, durationS: 1.2, note: 'zoom in' },
    { lat: 35.0150, lng: 33.7000, alt:  8000, heading: 45,  pitch: -90, durationS: 1.2, note: 'heading 45° at zoom' },
    { lat: 34.9800, lng: 33.6500, alt: 25000, heading: 90,  pitch: -90, durationS: 1.2, note: 'pan SW + zoom out + heading 90°' },
    { lat: 34.9800, lng: 33.6500, alt: 25000, heading: 360, pitch: -90, durationS: 1.2, note: 'heading 360° (modulo 360 = 0)' },
  ].slice(0, ITERATIONS);

  const snapshots = [];
  for (let i = 0; i < targets.length; i++) {
    const t = targets[i];
    console.log(`\n--- Iter ${i+1}/${targets.length}: ${t.note} ---`);
    await flyAndSettle(pageA, t);
    const snap = await capture(pageA, `A-after-${i+1}`);
    console.log(`  URL: ${snap.url}`);
    console.log(`  camera: lat=${snap.camera.lat.toFixed(4)} lng=${snap.camera.lng.toFixed(4)} alt=${Math.round(snap.camera.alt)} heading=${snap.camera.heading.toFixed(1)}`);
    console.log(`  mode=${snap.mode} cachedDataLen=${snap.cachedDataLen} suppressHashWrite=${snap.suppressHashWrite}`);
    snapshots.push({ target: t, snapshot: snap });
  }

  // === Context B: for each snapshot URL, open fresh and probe ===
  const ctxB = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const results = [];

  for (let i = 0; i < snapshots.length; i++) {
    const { target, snapshot } = snapshots[i];
    const url = snapshot.url;
    console.log(`\n=== Context B iter ${i+1}: probe ${url} ===`);

    const pageB = await ctxB.newPage();
    await pageB.goto(url, { waitUntil: 'domcontentloaded' });

    const probes = [];
    for (const waitMs of B_WAITS) {
      await pageB.waitForTimeout(waitMs === B_WAITS[0] ? waitMs : waitMs - B_WAITS[B_WAITS.indexOf(waitMs)-1]);
      const cap = await capture(pageB, `B-iter${i+1}-${waitMs}ms`);
      probes.push({ waitMs, capture: cap });
      console.log(`  @${waitMs}ms: ready=${cap.ready} mode=${cap.mode} alt=${cap.ready ? Math.round(cap.camera.alt) : '?'} cachedDataLen=${cap.cachedDataLen}`);
    }

    const finalB = probes[probes.length - 1].capture;
    const deltas = diff(snapshot, finalB);
    results.push({
      iter: i+1,
      target,
      a: snapshot,
      b_probes: probes,
      b_final: finalB,
      deltas,
    });
    if (deltas.length === 0) console.log(`  ✅ no significant deltas`);
    else console.log(`  ⚠️  deltas: ${deltas.join('; ')}`);

    await pageB.close();
  }

  // Summary
  console.log('\n\n========== SUMMARY ==========');
  for (const r of results) {
    const tag = r.deltas.length === 0 ? '✅' : '⚠️ ';
    console.log(`${tag} iter ${r.iter} (${r.target.note}): ${r.deltas.length ? r.deltas.join('; ') : 'match'}`);
  }

  // Persist
  const fs = require('fs');
  fs.writeFileSync('/tmp/url_roundtrip_log.json', JSON.stringify({
    site: SITE,
    start: START_HASH,
    timestamp: new Date().toISOString(),
    iterations: results,
  }, null, 2));
  console.log('\nFull log: /tmp/url_roundtrip_log.json');

  await browser.close();
})().catch(err => {
  console.error('FATAL:', err);
  process.exit(1);
});
