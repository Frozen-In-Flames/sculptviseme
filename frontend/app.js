/* SculptViseme app: step orchestration, the word-clip
 * sequencer, grade controls, and local exports.
 *
 * Video export follows Reactor's pattern: canvas.captureStream(30)
 * plus the Web Audio MediaStreamDestination track, MediaRecorder
 * with the same MIME fallback list (MP4 first, which is the entry
 * iOS Safari actually records through 18.3).
 */
import { StudioViewer, GRADE_DEFAULTS } from './viewer.js';

const MIME = ['video/mp4;codecs=avc1.42E01E,mp4a.40.2',
  'video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus',
  'video/webm'];

const $ = (id) => document.getElementById(id);
const viewer = new StudioViewer($('stage'));
$('stageLoading').textContent = 'Load a model to begin.';

const state = {
  jobId: null,
  keyframes: null,
  grade: JSON.parse(JSON.stringify(GRADE_DEFAULTS)),
};

/* ---------------- compute runner ----------------
 * The heavy stages run on a runner: this device (the local
 * backend serving this page, the default) or a cloud runner the
 * user points at. The choice is a user preference, stored in
 * localStorage; nothing about the pipeline changes with it, only
 * where the job endpoints are called.
 */
const compute = {
  mode: localStorage.getItem('sv_compute_mode') || 'local',
  url: localStorage.getItem('sv_cloud_url') || '',
  token: localStorage.getItem('sv_cloud_token') || '',
};

function apiBase() {
  return compute.mode === 'cloud' ? compute.url.replace(/\/+$/, '') : '';
}

async function apiFetch(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (compute.mode === 'cloud' && compute.token) {
    headers['Authorization'] = 'Bearer ' + compute.token;
  }
  return fetch(apiBase() + path, { ...opts, headers });
}

function initComputeUI() {
  const sel = $('computeMode');
  const fields = $('cloudFields');
  sel.value = compute.mode;
  $('cloudUrl').value = compute.url;
  $('cloudToken').value = compute.token;
  fields.style.display = compute.mode === 'cloud' ? 'block' : 'none';
  sel.addEventListener('change', () => {
    compute.mode = sel.value;
    localStorage.setItem('sv_compute_mode', compute.mode);
    fields.style.display = compute.mode === 'cloud' ? 'block' : 'none';
  });
  const save = () => {
    compute.url = $('cloudUrl').value.trim();
    compute.token = $('cloudToken').value.trim();
    localStorage.setItem('sv_cloud_url', compute.url);
    localStorage.setItem('sv_cloud_token', compute.token);
  };
  $('cloudUrl').addEventListener('change', save);
  $('cloudToken').addEventListener('change', save);
  $('checkRunnerBtn').addEventListener('click', async () => {
    save();
    const st = $('computeStatus');
    st.textContent = 'Checking…';
    try {
      const res = await fetch(apiBase() + '/api/health');
      const body = await res.json();
      if (!body.ok) throw new Error('health not ok');
      st.textContent =
        `Runner answers: SculptViseme in ${body.mode} mode` +
        (body.auth_required ? ', token required.' : ', no token.') +
        (compute.mode === 'cloud'
          ? ' Jobs will run on the cloud runner.'
          : ' Jobs will run on this device.');
    } catch (err) {
      st.textContent = 'Runner not reachable at that address.';
    }
  });
}
initComputeUI();

/* ---------------- sequencer ---------------- */

class Sequencer {
  constructor(viewer) {
    this.viewer = viewer;
    this.doc = null;
    this.buffers = [];       // AudioBuffers, aligned to doc.words
    this.ctx = null;
    this.dest = null;        // MediaStreamDestination for recording
    this.playing = false;
    this._raf = 0;
    this._finish = null;
    this.onWord = null;
    this.mode = null;        // 'audio' | 'silent'
  }

  ensureCtx() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.dest = this.ctx.createMediaStreamDestination();
    }
    return this.ctx;
  }

  setKeyframes(doc) {
    this.doc = doc;
    this.buffers = new Array(doc.words.length).fill(null);
  }

  async addWordFiles(files) {
    const ctx = this.ensureCtx();
    const sorted = [...files].sort((a, b) => a.name.localeCompare(b.name));
    const out = [];
    for (const f of sorted) {
      const buf = await ctx.decodeAudioData(await f.arrayBuffer());
      out.push(buf);
    }
    // Files are matched to words by order when counts agree;
    // otherwise they fill from the first word.
    for (let i = 0; i < out.length && i < this.buffers.length; i++) {
      this.buffers[i] = out[i];
    }
    return out.length;
  }

  _frameAt(t) {
    const frames = this.doc.frames;
    let lo = 0, hi = frames.length - 1, ans = null;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (frames[mid].t <= t) { ans = frames[mid]; lo = mid + 1; }
      else hi = mid - 1;
    }
    return ans;
  }

  play({ audio = true } = {}) {
    if (!this.doc || this.playing) return Promise.resolve(false);
    const doc = this.doc;
    const useAudio = audio && this.buffers.some(Boolean);
    this.mode = useAudio ? 'audio' : 'silent';
    this.playing = true;
    let t0;
    if (useAudio) {
      const ctx = this.ensureCtx();
      ctx.resume();
      t0 = ctx.currentTime + 0.06;
      doc.words.forEach((w, i) => {
        const buf = this.buffers[i];
        if (!buf) return;
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(ctx.destination);
        src.connect(this.dest);
        src.start(t0 + w.start);
      });
    }
    const startStamp = performance.now();
    const now = () => useAudio
      ? this.ctx.currentTime - t0
      : (performance.now() - startStamp) / 1000;
    return new Promise((resolve) => {
      this._finish = (ok) => {
        cancelAnimationFrame(this._raf);
        this.playing = false;
        this.viewer.zeroWeights();
        if (this.onWord) this.onWord(-1);
        resolve(ok);
      };
      const step = () => {
        if (!this.playing) return;
        const t = now();
        if (t >= doc.duration + 0.05) { this._finish(true); return; }
        const frame = this._frameAt(t);
        if (frame) {
          this.viewer.applyWeights(doc.visemes, frame.weights);
        }
        if (this.onWord) {
          const wi = doc.words.findIndex((w) => t >= w.start && t < w.end);
          this.onWord(wi);
        }
        this._raf = requestAnimationFrame(step);
      };
      step();
    });
  }

  stop() {
    if (this._finish) this._finish(false);
    this.playing = false;
  }
}

const seq = new Sequencer(viewer);

/* ---------------- step nav ---------------- */

$('stepNav').addEventListener('click', (e) => {
  const a = e.target.closest('a[data-step]');
  if (!a) return;
  document.querySelectorAll('#stepNav a')
    .forEach((x) => x.classList.toggle('active', x === a));
});

/* ---------------- upload step ---------------- */

function setUploadStatus(t) { $('uploadStatus').textContent = t; }

$('bundleFile').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  setUploadStatus('Validating bundle on the compute runner…');
  try {
    const fd = new FormData();
    fd.append('bundle', f);
    const res = await apiFetch('/api/bundles', { method: 'POST', body: fd });
    const body = await res.json();
    if (!res.ok || !body.ok) {
      const errs = body.report ? body.report.errors.join(' · ') : res.status;
      setUploadStatus('Bundle rejected: ' + errs);
      return;
    }
    state.jobId = body.job_id;
    $('runLipsyncBtn').disabled = false;
    setUploadStatus(`Job ${body.job_id} opened (regime ${body.regime}). ` +
      'Words in this bundle feed the lip-sync step.');
  } catch (err) {
    setUploadStatus('Runner not reachable. Check the Compute ' +
      'setting above: local mode needs this page served through ' +
      'the backend; cloud mode needs the runner URL to answer.');
  }
});

async function loadModel(source, name) {
  $('stageLoading').style.display = 'flex';
  $('stageLoading').textContent = 'Loading the sculpt…';
  try {
    const info = await viewer.loadGLB(source, name);
    $('stageLoading').style.display = 'none';
    $('modelStatus').textContent =
      `${name}: ${info.vertices.toLocaleString()} vertices` +
      (info.morphNames.length
        ? `, ${info.morphNames.length} morph targets (${info.morphNames.join(', ')}).`
        : ', no morph targets (lip-sync playback needs a morph-carrying export).');
    $('dlGlbBtn').disabled = false;
    $('dlStlBtn').disabled = false;
    $('dlUsdzBtn').disabled = false;
  } catch (err) {
    $('stageLoading').textContent = 'The model could not load: ' + err.message;
    $('modelStatus').textContent = 'No model on stage.';
  }
}

$('glbFile').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  await loadModel(await f.arrayBuffer(), f.name);
});

$('demoBtn').addEventListener('click', () =>
  loadModel('/demo/clay-bust-v3.glb', 'clay-bust-v3.glb'));

/* ---------------- lip-sync step ---------------- */

function renderWordList() {
  const el = $('wordList');
  el.innerHTML = '';
  const words = state.keyframes ? state.keyframes.words : [];
  words.forEach((w, i) => {
    const s = document.createElement('span');
    s.className = 'w';
    s.textContent = w.text;
    s.dataset.idx = i;
    el.appendChild(s);
  });
}

seq.onWord = (idx) => {
  document.querySelectorAll('#wordList .w').forEach((el) => {
    el.classList.toggle('playing', Number(el.dataset.idx) === idx);
  });
};

function setKeyframes(doc, note) {
  state.keyframes = doc;
  seq.setKeyframes(doc);
  renderWordList();
  $('playBtn').disabled = false;
  $('dlKeyBtn').disabled = false;
  $('recordBtn').disabled = false;
  $('syncStatus').textContent =
    `${doc.words.length} words, ${doc.frames.length} frames at ` +
    `${doc.fps} fps, ${doc.duration}s. ${note || ''}`;
}

$('runLipsyncBtn').addEventListener('click', async () => {
  if (!state.jobId) return;
  $('syncStatus').textContent = 'Running the aligner…';
  try {
    const res = await apiFetch(`/api/jobs/${state.jobId}/lipsync`,
      { method: 'POST' });
    if (!res.ok) throw new Error('aligner returned ' + res.status);
    setKeyframes(await res.json(), 'From the backend aligner.');
  } catch (err) {
    $('syncStatus').textContent = 'Lip-sync failed: ' + err.message;
  }
});

$('keyframesFile').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    setKeyframes(JSON.parse(await f.text()), 'Loaded from file.');
  } catch (err) {
    $('syncStatus').textContent = 'Keyframes file unreadable: ' + err.message;
  }
});

$('wordFiles').addEventListener('change', async (e) => {
  if (!state.keyframes) {
    $('syncStatus').textContent = 'Load keyframes first, then the word clips.';
    return;
  }
  const n = await seq.addWordFiles(e.target.files);
  $('syncStatus').textContent =
    `${n} word clip(s) decoded and matched to the sequence by order.`;
});

$('playBtn').addEventListener('click', async () => {
  $('playBtn').disabled = true;
  $('stopBtn').disabled = false;
  await seq.play({ audio: true });
  $('playBtn').disabled = false;
  $('stopBtn').disabled = true;
});

$('stopBtn').addEventListener('click', () => seq.stop());

/* ---------------- grade step ---------------- */

function sliderRow(parent, label, min, max, step, value, oninput) {
  const row = document.createElement('div');
  row.className = 'slider';
  const lab = document.createElement('label');
  lab.textContent = label;
  const input = document.createElement('input');
  input.type = 'range';
  input.min = min; input.max = max; input.step = step; input.value = value;
  const val = document.createElement('span');
  val.className = 'val';
  val.textContent = Number(value).toFixed(2);
  input.addEventListener('input', () => {
    val.textContent = Number(input.value).toFixed(2);
    oninput(Number(input.value));
  });
  row.append(lab, input, val);
  parent.appendChild(row);
  return input;
}

function buildGradeControls() {
  const chans = ['C', 'M', 'Y'];
  for (const zone of ['inkShadow', 'inkMid', 'inkHigh']) {
    const host = document.querySelector(`[data-zone="${zone}"]`);
    chans.forEach((ch, i) => {
      sliderRow(host, `${zone.replace('ink', '')} ${ch}`, 0, 1, 0.01, 0,
        (v) => {
          state.grade[zone][i] = v;
          viewer.setGrade({ [zone]: state.grade[zone] });
        });
    });
  }
  const plate = document.querySelector('[data-zone="plate"]');
  sliderRow(plate, 'K gain', 0, 2, 0.01, 1, (v) => {
    state.grade.kGain = v; viewer.setGrade({ kGain: v });
  });
  sliderRow(plate, 'K gamma', 0.2, 3, 0.01, 1, (v) => {
    state.grade.kGamma = v; viewer.setGrade({ kGamma: v });
  });
  const rgb = document.querySelector('[data-zone="rgb"]');
  sliderRow(rgb, 'Lift', -0.2, 0.2, 0.005, 0, (v) => {
    state.grade.rgbLift = [v, v, v];
    viewer.setGrade({ rgbLift: state.grade.rgbLift });
  });
  sliderRow(rgb, 'Gamma', 0.2, 3, 0.01, 1, (v) => {
    state.grade.rgbGamma = [v, v, v];
    viewer.setGrade({ rgbGamma: state.grade.rgbGamma });
  });
  sliderRow(rgb, 'Gain', 0, 2, 0.01, 1, (v) => {
    state.grade.rgbGain = [v, v, v];
    viewer.setGrade({ rgbGain: state.grade.rgbGain });
  });
}
buildGradeControls();

$('resetGradeBtn').addEventListener('click', () => {
  state.grade = JSON.parse(JSON.stringify(GRADE_DEFAULTS));
  viewer.setGrade(state.grade);
  document.querySelectorAll('#step-grade input[type="range"]')
    .forEach((i) => { i.value = i.defaultValue; });
});

/* ---------------- export step ---------------- */

function download(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

$('dlGlbBtn').addEventListener('click', () => {
  if (!viewer.modelBytes) return;
  download(new Blob([viewer.modelBytes], { type: 'model/gltf-binary' }),
    viewer.modelName || 'model.glb');
});

/* Binary STL from the loaded model, built in the page from the
 * stage geometry (neutral pose, world transforms applied). It
 * mirrors backend/stl_exporter.py: 80-byte zero header, triangle
 * count, per-face normals computed from the geometry, attribute
 * byte count zero. Static geometry only: no morph targets, no
 * animation, no color, no grade. */
function buildStlBytes() {
  const tris = [];
  viewer.group.updateMatrixWorld(true);
  viewer.group.traverse((o) => {
    if (!o.isMesh || !o.geometry) return;
    const geo = o.geometry;
    const pos = geo.attributes.position;
    if (!pos) return;
    const m = o.matrixWorld.elements;
    const v = new Float32Array(pos.count * 3);
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      v[i * 3] = m[0] * x + m[4] * y + m[8] * z + m[12];
      v[i * 3 + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
      v[i * 3 + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
    }
    const idx = geo.index ? geo.index.array : null;
    const n = idx ? idx.length : pos.count;
    for (let t = 0; t + 2 < n; t += 3) {
      const a = idx ? idx[t] : t, b = idx ? idx[t + 1] : t + 1,
        c = idx ? idx[t + 2] : t + 2;
      tris.push([v[a * 3], v[a * 3 + 1], v[a * 3 + 2],
                 v[b * 3], v[b * 3 + 1], v[b * 3 + 2],
                 v[c * 3], v[c * 3 + 1], v[c * 3 + 2]]);
    }
  });
  const buf = new ArrayBuffer(84 + tris.length * 50);
  const dv = new DataView(buf);
  dv.setUint32(80, tris.length, true);
  tris.forEach((tri, i) => {
    const o = 84 + i * 50;
    const ux = tri[3] - tri[0], uy = tri[4] - tri[1], uz = tri[5] - tri[2];
    const wx = tri[6] - tri[0], wy = tri[7] - tri[1], wz = tri[8] - tri[2];
    let nx = uy * wz - uz * wy, ny = uz * wx - ux * wz,
      nz = ux * wy - uy * wx;
    const len = Math.hypot(nx, ny, nz);
    if (len > 0) { nx /= len; ny /= len; nz /= len; }
    dv.setFloat32(o, nx, true);
    dv.setFloat32(o + 4, ny, true);
    dv.setFloat32(o + 8, nz, true);
    tri.forEach((c, j) => dv.setFloat32(o + 12 + j * 4, c, true));
    dv.setUint16(o + 48, 0, true);
  });
  return buf;
}

function baseName(ext) {
  return (viewer.modelName || 'model').replace(/\.[^.]+$/, '') + ext;
}

$('dlStlBtn').addEventListener('click', () => {
  if (!viewer.modelBytes) return;
  download(new Blob([buildStlBytes()], { type: 'model/stl' }),
    baseName('.stl'));
  $('exportStatus').textContent =
    'STL saved: static geometry only (no morphs, animation, or grade).';
});

$('dlUsdzBtn').addEventListener('click', async () => {
  if (!viewer.modelBytes) return;
  $('exportStatus').textContent = 'Building the static USDZ on the compute runner…';
  try {
    const fd = new FormData();
    fd.append('mesh', new Blob([viewer.modelBytes],
      { type: 'model/gltf-binary' }), viewer.modelName || 'model.glb');
    const res = await apiFetch('/api/glb-usdz', { method: 'POST', body: fd });
    if (!res.ok) {
      let detail = 'backend returned ' + res.status;
      try { detail = (await res.json()).detail || detail; } catch { /* keep status */ }
      throw new Error(detail);
    }
    download(await res.blob(), baseName('.usdz'));
    $('exportStatus').textContent =
      'USDZ saved: static neutral pose only (no morphs or animation).';
  } catch (err) {
    $('exportStatus').textContent =
      'USDZ export unavailable: ' + err.message +
      ' (USDZ is built by the compute runner; check the Compute setting above.)';
  }
});

$('dlKeyBtn').addEventListener('click', () => {
  if (!state.keyframes) return;
  download(new Blob([JSON.stringify(state.keyframes, null, 2)],
    { type: 'application/json' }), 'keyframes.json');
});

$('recordBtn').addEventListener('click', async () => {
  if (!state.keyframes) return;
  $('recordBtn').disabled = true;
  $('exportStatus').textContent = 'Recording the sequence…';
  try {
    seq.ensureCtx();
    const canvas = viewer.renderer.domElement;
    const stream = new MediaStream([
      ...canvas.captureStream(30).getVideoTracks(),
      ...seq.dest.stream.getAudioTracks()]);
    const mt = MIME.find((t) => MediaRecorder.isTypeSupported(t)) || '';
    const mr = new MediaRecorder(stream,
      { mimeType: mt, videoBitsPerSecond: 8e6 });
    const chunks = [];
    mr.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    const stopped = new Promise((r) => { mr.onstop = r; });
    mr.start();
    await seq.play({ audio: true });
    setTimeout(() => mr.stop(), 250);
    await stopped;
    const type = mt.split(';')[0] || 'video/webm';
    download(new Blob(chunks, { type }),
      'clay-sculpt-lipsync.' + (type.includes('mp4') ? 'mp4' : 'webm'));
    $('exportStatus').textContent = 'Video saved to downloads.';
  } catch (err) {
    $('exportStatus').textContent = 'Recording failed: ' + err.message;
  }
  $('recordBtn').disabled = false;
});

/* ---------------- verification hooks ---------------- */

window.__studio = {
  ready: true,
  viewer,
  sequencer: seq,
  state,
  loadModel,
  setKeyframes,
  setGrade: (patch) => {
    Object.assign(state.grade, patch);
    viewer.setGrade(patch);
  },
  getInfluences: () => viewer.getInfluences(),
  buildStlBytes,
};
