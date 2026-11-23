/* Clay Sculpt Studio viewer: Three.js stage for the clay bust.
 *
 * Clay material: MeshStandardMaterial with the grading stage from
 * shaders/clay_grade.frag injected after the colorspace fragment,
 * so grade() receives display-referred color exactly as the shader
 * contract states (gradeCMYK first, RGB lift/gamma/gain second).
 * The same frag file is the one the NumPy parity test checks, so
 * the page and the backend reference cannot drift apart.
 *
 * Morph targets: GLTFLoader surfaces them as morphTargetInfluences
 * with names from the GLB extras; applyWeights takes weights in the
 * keyframes document's viseme order and maps by name.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export const GRADE_DEFAULTS = {
  inkShadow: [0, 0, 0], inkMid: [0, 0, 0], inkHigh: [0, 0, 0],
  kGain: 1.0, kGamma: 1.0,
  rgbLift: [0, 0, 0], rgbGamma: [1, 1, 1], rgbGain: [1, 1, 1],
};

export class StudioViewer {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b0b0f);
    this.camera = new THREE.PerspectiveCamera(
      34, container.clientWidth / container.clientHeight, 0.1, 100);
    this.camera.position.set(0.3, 0.15, 3.4);
    this.renderer = new THREE.WebGLRenderer({ antialias: true,
      preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    this.renderer.toneMapping = THREE.NoToneMapping;
    container.appendChild(this.renderer.domElement);

    const hemi = new THREE.HemisphereLight(0xffffff, 0x35322e, 0.7);
    const key = new THREE.DirectionalLight(0xfff1e0, 3.2);
    key.position.set(0.6, 1.0, 4.6);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5);
    fill.position.set(-3, 0.5, 2);
    const rim = new THREE.DirectionalLight(0xffffff, 1.1);
    rim.position.set(-1.5, 2, -3);
    this.scene.add(hemi, key, fill, rim);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.enablePan = false;

    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.morphMesh = null;
    this.morphNames = [];
    this.modelBytes = null;
    this.modelName = null;

    this.gradeUniforms = {
      inkShadow: { value: new THREE.Vector3(...GRADE_DEFAULTS.inkShadow) },
      inkMid: { value: new THREE.Vector3(...GRADE_DEFAULTS.inkMid) },
      inkHigh: { value: new THREE.Vector3(...GRADE_DEFAULTS.inkHigh) },
      kGain: { value: GRADE_DEFAULTS.kGain },
      kGamma: { value: GRADE_DEFAULTS.kGamma },
      rgbLift: { value: new THREE.Vector3(...GRADE_DEFAULTS.rgbLift) },
      rgbGamma: { value: new THREE.Vector3(...GRADE_DEFAULTS.rgbGamma) },
      rgbGain: { value: new THREE.Vector3(...GRADE_DEFAULTS.rgbGain) },
    };
    this._gradeGLSL = null;

    new ResizeObserver(() => {
      const w = container.clientWidth, h = container.clientHeight;
      if (!w || !h) return;
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(w, h);
    }).observe(container);

    const tick = () => {
      requestAnimationFrame(tick);
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
    tick();
  }

  async _loadGradeGLSL() {
    if (this._gradeGLSL) return this._gradeGLSL;
    const res = await fetch('shaders/clay_grade.frag');
    if (!res.ok) throw new Error('grading shader failed to load');
    const text = await res.text();
    // Three prepends its own precision and uniforms; drop the
    // file's precision line, keep its uniform declarations and
    // the grade functions verbatim.
    this._gradeGLSL = text.replace(/^\s*precision[^;]*;/m, '');
    return this._gradeGLSL;
  }

  _patchMaterial(material, glsl) {
    const uniforms = this.gradeUniforms;
    material.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, uniforms);
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>',
          '#include <common>\n' + glsl)
        .replace('#include <colorspace_fragment>',
          '#include <colorspace_fragment>\n' +
          '  gl_FragColor.rgb = grade(gl_FragColor.rgb);');
    };
    material.customProgramCacheKey = () => 'clay-grade-v1';
    return material;
  }

  async loadGLB(source, name = 'model.glb') {
    const glsl = await this._loadGradeGLSL();
    const loader = new GLTFLoader();
    let gltf;
    if (typeof source === 'string') {
      const res = await fetch(source);
      if (!res.ok) throw new Error(`model fetch failed: ${res.status}`);
      this.modelBytes = await res.arrayBuffer();
      gltf = await loader.parseAsync(this.modelBytes, '');
    } else {
      this.modelBytes = source;
      gltf = await loader.parseAsync(source, '');
    }
    this.modelName = name;
    this.group.clear();
    this.morphMesh = null;
    this.morphNames = [];
    const model = gltf.scene;
    model.traverse((o) => {
      if (o.isMesh) {
        const hasColor = !!o.geometry.getAttribute('color');
        if (!o.geometry.getAttribute('normal')) {
          o.geometry.computeVertexNormals();
        }
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        const patched = mats.map((m) => {
          const c = m.clone();
          if (hasColor) c.vertexColors = true;
          if ('roughness' in c) c.roughness = Math.max(c.roughness, 0.55);
          return this._patchMaterial(c, glsl);
        });
        o.material = Array.isArray(o.material) ? patched : patched[0];
        if (o.morphTargetInfluences && o.morphTargetInfluences.length) {
          this.morphMesh = o;
          const dict = o.morphTargetDictionary || {};
          this.morphNames = Object.keys(dict)
            .sort((a, b) => dict[a] - dict[b]);
        }
      }
    });
    const box = new THREE.Box3().setFromObject(model);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    model.position.set(-center.x, -center.y, -center.z);
    this.group.add(model);
    const radius = Math.max(size.x, size.y, size.z) * 0.5 || 1;
    this.camera.position.set(0.3, 0.15, radius * 3.4);
    this.controls.target.set(0, 0, 0);
    this.controls.update();
    return { morphNames: this.morphNames,
             vertices: this._countVertices(model) };
  }

  _countVertices(model) {
    let n = 0;
    model.traverse((o) => {
      if (o.isMesh) n += o.geometry.getAttribute('position').count;
    });
    return n;
  }

  setGrade(patch) {
    for (const [k, v] of Object.entries(patch)) {
      const u = this.gradeUniforms[k];
      if (!u) continue;
      if (Array.isArray(v)) u.value.set(v[0], v[1], v[2]);
      else u.value = v;
    }
  }

  getGrade() {
    const g = {};
    for (const [k, u] of Object.entries(this.gradeUniforms)) {
      g[k] = u.value.isVector3 ? u.value.toArray() : u.value;
    }
    return g;
  }

  /* weights: array aligned to `names` (the keyframes viseme order).
   * Names the model does not carry are ignored. */
  applyWeights(names, weights) {
    if (!this.morphMesh) return 0;
    const dict = this.morphMesh.morphTargetDictionary || {};
    let applied = 0;
    for (let i = 0; i < names.length; i++) {
      const idx = dict[names[i]];
      if (idx !== undefined) {
        this.morphMesh.morphTargetInfluences[idx] = weights[i] || 0;
        applied++;
      }
    }
    return applied;
  }

  zeroWeights() {
    if (!this.morphMesh) return;
    this.morphMesh.morphTargetInfluences.fill(0);
  }

  getInfluences() {
    if (!this.morphMesh) return { names: [], weights: [] };
    return { names: this.morphNames,
             weights: [...this.morphMesh.morphTargetInfluences] };
  }
}
