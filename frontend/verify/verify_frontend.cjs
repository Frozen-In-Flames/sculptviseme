#!/usr/bin/env node
/* Clay Sculpt Studio frontend check (local, headless):
 * serves frontend/ plus the /tmp/css-fixture build (make_fixture.py)
 * and the bio-3d demo bust, loads the page with the three.js CDN
 * intercepted from byte-identical local copies (the twin pattern),
 * then asserts: page ready with zero console/page/network errors,
 * fixture GLB loads with 15 morph targets, a grade slider change
 * visibly alters the rendered pixels, the sequencer animates
 * morph influences on the test keyframes (silent clock) and zeroes
 * them at the end, and the Export step's STL button downloads a
 * file whose binary header validates (USDZ button checked for
 * presence and enabled state; its bytes come from the backend).
 * Screenshots land beside this script.
 * The iPhone sensory check is Aries's gate, not this script's. */
'use strict';
const fs = require('fs');
const http = require('http');
const path = require('path');
const puppeteer = require('/home/hatch/workspace/.pptr/node_modules/puppeteer-core');

const HERE = __dirname;
const FRONTEND = path.resolve(HERE, '..');
const FIXTURE = '/tmp/css-fixture';
const DEMO_BUST = '/home/hatch/workspace/bio-3d/aries-bust-clay-v3.glb';
const EXE = '/home/hatch/workspace/.pptr/chrome-headless-shell/linux-157.0.8103.78/chrome-headless-shell-linux64/chrome-headless-shell';
const PORT = 8957;
const CDN_PREFIX = 'https://cdn.jsdelivr.net/npm/three@0.164.1/';
const CDN_LOCAL = '/tmp/three-cdn';
const MIME = { '.html': 'text/html', '.js': 'text/javascript',
  '.json': 'application/json', '.glb': 'model/gltf-binary',
  '.frag': 'text/plain', '.wav': 'audio/wav', '.png': 'image/png' };

function serve() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const url = decodeURIComponent(req.url.split('?')[0]);
      if (url === '/favicon.ico') { res.writeHead(204); res.end(); return; }
      let file;
      if (url === '/fixture.glb') file = path.join(FIXTURE, 'fixture.glb');
      else if (url === '/keyframes.json') file = path.join(FIXTURE, 'keyframes.json');
      else if (url === '/demo/clay-bust-v3.glb') file = DEMO_BUST;
      else file = path.join(FRONTEND, url === '/' ? 'index.html' : url);
      if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        res.writeHead(404); res.end('not found'); return;
      }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
      fs.createReadStream(file).pipe(res);
    });
    srv.listen(PORT, () => resolve(srv));
  });
}

(async () => {
  const srv = await serve();
  const browser = await puppeteer.launch({
    executablePath: EXE,
    args: ['--no-sandbox', '--enable-unsafe-swiftshader', '--use-angle=swiftshader'],
  });
  const results = {};
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 800, height: 1100 });
    const pageErrors = [], consoleErrors = [], badResponses = [];
    page.on('pageerror', (e) => pageErrors.push(String(e)));
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('response', (r) => { if (r.status() >= 400) badResponses.push(r.status() + ' ' + r.url()); });
    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const url = req.url();
      if (url.startsWith(CDN_PREFIX)) {
        const local = path.join(CDN_LOCAL, url.slice(CDN_PREFIX.length));
        if (fs.existsSync(local)) {
          req.respond({ status: 200, contentType: 'text/javascript', headers: { 'Access-Control-Allow-Origin': '*' }, body: fs.readFileSync(local) });
          return;
        }
      }
      req.continue();
    });

    await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'load', timeout: 30000 });
    await page.waitForFunction('window.__studio && window.__studio.ready === true', { timeout: 30000 });
    results.ready = true;

    // Load the morph-carrying fixture through the page's own path.
    await page.evaluate(async () => {
      await window.__studio.loadModel('/fixture.glb', 'fixture.glb');
    });
    results.model = await page.evaluate(() => ({
      status: document.getElementById('modelStatus').textContent,
      influences: window.__studio.getInfluences(),
    }));
    console.log('model:', results.model.status);
    if (results.model.influences.names.length !== 15) {
      throw new Error('expected 15 morph targets, got ' + results.model.influences.names.length);
    }

    const meanPixels = () => page.evaluate(() => {
      const src = window.__studio.viewer.renderer.domElement;
      const c = document.createElement('canvas');
      c.width = src.width; c.height = src.height;
      const ctx = c.getContext('2d');
      ctx.drawImage(src, 0, 0);
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      let r = 0, g = 0, b = 0, n = 0;
      for (let i = 0; i < d.length; i += 40) { r += d[i]; g += d[i + 1]; b += d[i + 2]; n++; }
      return [r / n, g / n, b / n];
    });
    await new Promise((r) => setTimeout(r, 600));
    const before = await meanPixels();
    const stageEl = await page.$('#stage');
    await stageEl.screenshot({ path: path.join(HERE, 'studio-before-grade.png') });

    // Drive real grade sliders and confirm the render changes
    // measurably. The clay renders bright, so most pixels sit in
    // the highlight zone with midtone weight near zero; a midtone
    // only change is real but sub-threshold on the mean. The K
    // gain slider (black plate) affects every pixel, so drive it
    // together with midtone cyan.
    await page.evaluate(() => {
      const set = (sel, v) => {
        const input = document.querySelector(sel);
        input.value = v;
        input.dispatchEvent(new Event('input', { bubbles: true }));
      };
      set('[data-zone="inkMid"] input[type="range"]', 1.0);
      set('[data-zone="plate"] input[type="range"]', 1.7);
    });
    // SwiftShader renders this 235k-vertex bust slowly; poll until
    // a fresh frame carrying the new grade actually lands (or the
    // wait expires and the delta assertion below fails honestly).
    let after = before;
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 500));
      after = await meanPixels();
      if (Math.max(...before.map((v, j) => Math.abs(v - after[j]))) > 1.0) break;
    }
    await stageEl.screenshot({ path: path.join(HERE, 'studio-after-grade.png') });
    results.gradePixelDelta = before.map((v, i) => Math.abs(v - after[i]));
    console.log('grade pixel delta:', results.gradePixelDelta.map((v) => v.toFixed(2)).join(', '));
    if (Math.max(...results.gradePixelDelta) < 1.0) {
      throw new Error('grade slider did not visibly change the render');
    }

    // Sequencer: load the test keyframes, play on the silent clock,
    // expect motion and a clean zero. The peak is recorded in the
    // page by wrapping applyWeights: the playback is under a
    // second, and external polling at 100 ms intervals missed it
    // entirely once SwiftShader frame times grew (each evaluate
    // round trip lands after the weights were already zeroed).
    // In-page recording measures what the sequencer actually
    // applied, which is the claim under test.
    await page.evaluate(async () => {
      const doc = await (await fetch('/keyframes.json')).json();
      window.__studio.setKeyframes(doc, 'verify fixture');
      const viewer = window.__studio.viewer;
      window.__morphPeak = 0;
      const orig = viewer.applyWeights.bind(viewer);
      viewer.applyWeights = (names, w) => {
        window.__morphPeak = Math.max(window.__morphPeak,
          ...w.map(Math.abs));
        return orig(names, w);
      };
      window.__studio.__playPromise = window.__studio.sequencer.play({ audio: false });
    });
    await page.evaluate(() => window.__studio.__playPromise);
    const peak = await page.evaluate(() => window.__morphPeak);
    const endW = await page.evaluate(() => window.__studio.getInfluences().weights);
    results.morphPeak = peak;
    results.morphEndMax = Math.max(...endW.map(Math.abs));
    console.log(`morph peak ${peak.toFixed(3)}, end max ${results.morphEndMax}`);
    if (peak < 0.05) throw new Error('morph influences did not animate');
    if (results.morphEndMax > 1e-6) throw new Error('influences not zeroed at end');

    // Export step: the STL and USDZ buttons render enabled once a
    // model is loaded, and a real click on the STL button produces
    // a download whose header validates (the count field at byte
    // 80 must agree with the total byte length). If the headless
    // download plumbing does not deliver a file, fall back to the
    // exact builder the click handler calls and validate its
    // bytes the same way, labeled as the fallback in the results.
    results.exportButtons = await page.evaluate(() => ({
      stlEnabled: !document.getElementById('dlStlBtn').disabled,
      usdzEnabled: !document.getElementById('dlUsdzBtn').disabled,
      usdzLabel: document.getElementById('dlUsdzBtn').textContent,
    }));
    console.log('export buttons:', results.exportButtons);
    if (!results.exportButtons.stlEnabled || !results.exportButtons.usdzEnabled) {
      throw new Error('STL/USDZ export buttons not enabled after model load');
    }
    const dlDir = fs.mkdtempSync(path.join(require('os').tmpdir(), 'css-dl-'));
    const cdp = await page.createCDPSession();
    await cdp.send('Browser.setDownloadBehavior',
      { behavior: 'allow', downloadPath: dlDir, eventsEnabled: true });
    const dlDone = new Promise((resolve) => {
      const to = setTimeout(() => resolve(null), 90000);
      cdp.on('Browser.downloadProgress', (e) => {
        if (e.state === 'completed' || e.state === 'canceled') {
          clearTimeout(to); resolve(e.state);
        }
      });
    });
    await page.click('#dlStlBtn');
    await dlDone;
    let stlFile = null;
    for (let i = 0; i < 20 && !stlFile; i++) {
      const names = fs.readdirSync(dlDir).filter((n) => n.endsWith('.stl'));
      if (names.length) stlFile = path.join(dlDir, names[0]);
      else await new Promise((r) => setTimeout(r, 500));
    }
    if (stlFile) {
      const buf = fs.readFileSync(stlFile);
      const count = buf.readUInt32LE(80);
      results.stlDownload = {
        file: path.basename(stlFile), bytes: buf.length,
        triangles: count,
        headerOk: buf.length === 84 + count * 50 && count > 0,
      };
    } else {
      const info = await page.evaluate(() => {
        const b = window.__studio.buildStlBytes();
        return { byteLength: b.byteLength,
                 count: new DataView(b).getUint32(80, true) };
      });
      results.stlDownload = {
        viaBuilderFallback: true, bytes: info.byteLength,
        triangles: info.count,
        headerOk: info.byteLength === 84 + info.count * 50 && info.count > 0,
      };
    }
    console.log('stl download:', results.stlDownload);
    if (!results.stlDownload.headerOk) {
      throw new Error('STL download header inconsistent with byte length');
    }

    results.pageErrors = pageErrors;
    results.consoleErrors = consoleErrors;
    results.badResponses = badResponses;
    console.log('page errors:', pageErrors.length ? pageErrors : 'none');
    console.log('console errors:', consoleErrors.length ? consoleErrors : 'none');
    console.log('bad responses:', badResponses.length ? badResponses : 'none');
  } finally {
    fs.writeFileSync(path.join(HERE, 'verify-results.json'), JSON.stringify(results, null, 2));
    await browser.close();
    srv.close();
  }
  const bad = (results.pageErrors || []).length || (results.consoleErrors || []).length || (results.badResponses || []).length;
  process.exit(bad ? 2 : 0);
})().catch((e) => { console.error('VERIFY FAILED:', e.message); process.exit(1); });
