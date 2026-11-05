import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "CSRSecondPass";
const EVENT = "aicg3d_csr_progress";
const STYLE_ID = "aicg3d-csr-second-pass-style";
const STATE = new Map();
let listenerInstalled = false;

const CSS = `
.csr-sp { display:flex; flex-direction:column; gap:8px; width:100%; padding:8px 2px; color:var(--fg-color,#ddd); }
.csr-sp-head { display:flex; align-items:center; gap:8px; }
.csr-sp-title { color:#eef3fb; font-size:13px; font-weight:650; }
.csr-sp-tag { margin-left:auto; color:#8fa1b9; font-size:10px; }
.csr-sp-switch { width:46px; height:24px; border:1px solid #46536a; border-radius:999px; background:#262d38; position:relative; cursor:pointer; }
.csr-sp-switch::after { content:""; position:absolute; width:18px; height:18px; left:2px; top:2px; border-radius:50%; background:#8f9eb3; transition:left .16s ease,background .16s ease; }
.csr-sp-switch.on { border-color:#4b9b73; background:#214938; }
.csr-sp-switch.on::after { left:24px; background:#8fe1b2; }
.csr-sp-body { display:flex; flex-direction:column; gap:8px; }
.csr-sp-body[hidden] { display:none !important; }
.csr-sp-group { display:flex; flex-direction:column; gap:6px; padding:8px; border:1px solid #354253; border-radius:6px; background:#1b222c; }
.csr-sp-group > strong { color:#cbd7e8; font-size:10px; font-weight:600; }
.csr-sp-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }
.csr-sp-field { display:flex; flex-direction:column; gap:3px; min-width:0; color:#93a3b8; font-size:9px; }
.csr-sp-field.wide { grid-column:1/-1; }
.csr-sp-field select,.csr-sp-field input { width:100%; min-width:0; height:26px; border:1px solid #3e4a5f; border-radius:5px; background:#121820; color:#e5edf8; padding:0 6px; font-size:10px; }
.csr-sp-check { display:flex; align-items:center; gap:6px; min-height:26px; color:#aebbd0; font-size:10px; }
.csr-sp-check input { width:15px; height:15px; accent-color:#5d8fd8; }
.csr-sp-note { color:#8f9eb3; font-size:10px; line-height:1.4; }
.csr-sp-progress { height:7px; border-radius:999px; background:#2a303a; overflow:hidden; }
.csr-sp-progress > div { height:100%; width:0%; background:linear-gradient(90deg,#3d7ae8,#54b8d8); transition:width .2s ease; }
.csr-sp-status { display:grid; grid-template-columns:1fr 1fr; gap:3px 8px; color:#95a3b8; font-size:9px; }
.csr-sp-frame { position:relative; aspect-ratio:16/9; min-height:150px; max-height:260px; border:1px solid #343e4e; border-radius:6px; overflow:hidden; background:#090c11; }
.csr-sp-frame img,.csr-sp-frame video { width:100%; height:100%; object-fit:contain; display:block; }
.csr-sp-frame [hidden] { display:none !important; }
`;

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function widget(node, name) {
  return node.widgets?.find((item) => item.name === name);
}

function valuesOf(target) {
  const values = target?.options?.values;
  if (Array.isArray(values)) return values;
  if (typeof values === "function") {
    try { return values(); } catch { return []; }
  }
  return [];
}

function setWidget(node, target, value) {
  if (!target) return;
  target.value = value;
  target.callback?.(value);
  node.setDirtyCanvas?.(true, true);
  node.graph?.setDirtyCanvas?.(true, true);
}

function hideWidget(target) {
  if (!target) return;
  target.type = "hidden";
  target.computeSize = () => [0, -4];
  if (target.inputEl) target.inputEl.style.display = "none";
  if (target.element) target.element.style.display = "none";
}

function selectField(node, name, label, wide = false) {
  const field = el("label", `csr-sp-field${wide ? " wide" : ""}`);
  field.append(el("span", "", label));
  const select = el("select");
  const target = widget(node, name);
  for (const value of valuesOf(target)) select.append(new Option(String(value), String(value)));
  select.value = String(target?.value ?? "");
  select.onchange = () => setWidget(node, target, select.value);
  field.append(select);
  return { field, control: select, target, kind: "select" };
}

function numberField(node, name, label, step = "1") {
  const field = el("label", "csr-sp-field");
  field.append(el("span", "", label));
  const input = el("input");
  input.type = "number";
  input.step = step;
  const target = widget(node, name);
  input.min = String(target?.options?.min ?? "");
  input.max = String(target?.options?.max ?? "");
  input.value = String(target?.value ?? "");
  input.onchange = () => setWidget(node, target, Number(input.value));
  field.append(input);
  return { field, control: input, target, kind: "number" };
}

function checkField(node, name, label) {
  const field = el("label", "csr-sp-check");
  const input = el("input");
  input.type = "checkbox";
  const target = widget(node, name);
  input.checked = Boolean(target?.value);
  input.onchange = () => setWidget(node, target, input.checked);
  field.append(input, el("span", "", label));
  return { field, control: input, target, kind: "check" };
}

function newControls(node) {
  const controls = {};
  const register = (entry) => { controls[entry.target.name] = entry; return entry; };
  const modelGroup = el("div", "csr-sp-group");
  modelGroup.append(el("strong", "", "二采模型与放大"));
  const modelGrid = el("div", "csr-sp-grid");
  modelGrid.append(
    register(selectField(node, "second_pass_model", "二采主模型", true)).field,
    register(selectField(node, "second_pass_lora", "二采 LoRA")).field,
    register(numberField(node, "second_pass_lora_strength", "LoRA 强度", "0.05")).field,
    register(selectField(node, "latent_upscale_model", "Latent 放大器", true)).field,
    register(numberField(node, "upscale_scale", "放大倍率", "0.05")).field,
    register(selectField(node, "upscale_device", "放大器设备")).field,
    register(selectField(node, "upscale_precision", "放大器精度")).field,
    register(checkField(node, "upscale_chunking", "时间分块防爆显存")).field,
  );
  modelGroup.append(modelGrid);

  const sampleGroup = el("div", "csr-sp-group");
  sampleGroup.append(el("strong", "", "二采采样"));
  const sampleGrid = el("div", "csr-sp-grid");
  sampleGrid.append(
    register(numberField(node, "steps", "二采步数")).field,
    register(numberField(node, "denoise", "重画力度 denoise", "0.01")).field,
    register(selectField(node, "sampler_name", "采样器")).field,
    register(selectField(node, "scheduler", "调度器")).field,
    register(numberField(node, "seed", "二采种子")).field,
  );
  sampleGroup.append(sampleGrid);

  const runGroup = el("div", "csr-sp-group");
  runGroup.append(el("strong", "", "预览与断点"));
  const runGrid = el("div", "csr-sp-grid");
  runGrid.append(
    register(checkField(node, "resume_completed", "断点续跑")).field,
    register(checkField(node, "live_preview", "实时采样预览")).field,
    register(numberField(node, "preview_every_steps", "每隔几步预览")).field,
    register(selectField(node, "preview_resolution", "预览清晰度")).field,
  );
  runGroup.append(runGrid);

  const note = el("div", "csr-sp-note", "关闭二采时节点只透传一采结果，不加载任何二采模型。建议先用 1.5×、4 步、er_sde + beta、denoise 0.3。");
  const progress = el("div", "csr-sp-progress");
  const progressFill = el("div");
  progress.append(progressFill);
  const status = el("div", "csr-sp-status");
  const segmentText = el("span", "", "等待二采");
  const stepText = el("span", "", "采样 0/0");
  const fileText = el("span", "", "断点目录准备中");
  fileText.style.gridColumn = "1/-1";
  status.append(segmentText, stepText, fileText);
  const frame = el("div", "csr-sp-frame");
  const image = el("img");
  image.hidden = true;
  image.alt = "CSR second-pass preview";
  const video = el("video");
  video.hidden = true;
  video.controls = true;
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  frame.append(image, video);

  return {
    controls,
    body: [modelGroup, sampleGroup, runGroup, note, progress, status, frame],
    progressFill,
    segmentText,
    stepText,
    fileText,
    image,
    video,
  };
}

function syncControls(node, ui) {
  for (const entry of Object.values(ui.controls)) {
    const value = entry.target?.value;
    if (entry.kind === "check") entry.control.checked = Boolean(value);
    else if (entry.kind === "select") {
      const text = String(value ?? "");
      if (text && ![...entry.control.options].some((item) => item.value === text)) entry.control.append(new Option(text, text));
      entry.control.value = text;
    } else entry.control.value = String(value ?? "");
  }
}

function syncSize(node, ui) {
  const enabled = Boolean(widget(node, "enable_second_pass")?.value);
  ui.bodyContainer.hidden = !enabled;
  ui.switch.classList.toggle("on", enabled);
  ui.switch.title = enabled ? "关闭二采放大" : "开启二采放大";
  const panel = node._csrSecondPanel;
  if (!panel) return;
  const fallback = enabled ? 560 : 120;
  const measured = Math.ceil(node._csrRoot?.scrollHeight || 0);
  const panelHeight = enabled ? Math.max(fallback, measured + 12) : 120;
  const heightGetter = () => panelHeight;
  panel.getMinHeight = heightGetter;
  panel.getMaxHeight = heightGetter;
  if (panel.options) {
    panel.options.getMinHeight = heightGetter;
    panel.options.getMaxHeight = heightGetter;
  }
  panel.computedHeight = panelHeight;
  const computed = node.computeSize?.() || [540, panelHeight + 64];
  node.setSize?.([Math.max(540, computed[0] || 0), Math.max(panelHeight + 64, computed[1] || 0)]);
  node.setDirtyCanvas?.(true, true);
  node.graph?.setDirtyCanvas?.(true, true);
}

function updatePreview(node, ui, detail) {
  const percent = detail.done && detail.ok !== false ? 100 : Math.max(0, Math.min(100, Number(detail.overall || 0) * 100));
  ui.progressFill.style.width = `${percent.toFixed(2)}%`;
  ui.segmentText.textContent = `第 ${detail.segment_number || 0}/${detail.total_segments || 0} 段`;
  ui.stepText.textContent = `采样 ${Number(detail.step) || 0}/${Number(detail.steps) || 0}`;
  if (detail.preview_jpeg) {
    const prefix = ["data:", "image/jpeg", ";base64,"].join("");
    ui.image.src = prefix + detail.preview_jpeg;
    ui.image.hidden = false;
    ui.video.hidden = true;
    ui.video.pause?.();
  }
  if (detail.segment_file) {
    ui.video.src = `/view?filename=${encodeURIComponent(detail.segment_file)}&subfolder=${encodeURIComponent(detail.segment_subfolder || "")}&type=output&t=${Date.now()}`;
    ui.video.hidden = false;
    ui.image.hidden = true;
    ui.video.play?.().catch(() => {});
    ui.fileText.textContent = `已保存 ${detail.segment_file}`;
  }
  if (detail.phase === "error" || (detail.done && detail.ok === false)) {
    ui.fileText.textContent = detail.error ? `错误：${detail.error}` : "二采运行失败";
  }
}

function installListener() {
  if (listenerInstalled) return;
  listenerInstalled = true;
  api.addEventListener(EVENT, (event) => {
    const detail = event?.detail;
    if (!detail?.node_id) return;
    STATE.set(String(detail.node_id), detail);
    const node = (app.graph?._nodes || []).find((item) => String(item.id) === String(detail.node_id) && item.type === NODE_NAME);
    if (node?._csrSecondUi) updatePreview(node, node._csrSecondUi, detail);
  });
}

function createPanel(node) {
  ensureStyle();
  installListener();
  const root = el("div", "csr-sp");
  const head = el("div", "csr-sp-head");
  const toggleWidget = widget(node, "enable_second_pass");
  const switchButton = el("button", "csr-sp-switch");
  switchButton.type = "button";
  switchButton.onclick = (event) => {
    event.stopPropagation();
    setWidget(node, toggleWidget, !Boolean(toggleWidget?.value));
    syncSize(node, node._csrSecondUi);
    requestAnimationFrame(() => syncSize(node, node._csrSecondUi));
  };
  head.append(el("span", "csr-sp-title", "二采放大"), switchButton, el("span", "csr-sp-tag", "可选"));
  const created = newControls(node);
  const bodyContainer = el("div", "csr-sp-body");
  bodyContainer.append(...created.body);
  root.append(head, bodyContainer);
  root.onpointerdown = root.onmousedown = root.ontouchstart = (event) => event.stopPropagation();

  node._csrSecondUi = { ...created, switch: switchButton, bodyContainer };
  node._csrRoot = root;
  for (const entry of Object.values(created.controls)) hideWidget(entry.target);
  hideWidget(widget(node, "control_after_generate"));
  hideWidget(toggleWidget);
  node._csrSecondPanel = node.addDOMWidget("csr_second_pass_panel", "AICG3D_CSR_SECOND_PASS", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 120,
    getMaxHeight: () => 4096,
  });
  syncControls(node, node._csrSecondUi);
  setTimeout(() => {
    syncSize(node, node._csrSecondUi);
    requestAnimationFrame(() => syncSize(node, node._csrSecondUi));
  }, 0);
}

app.registerExtension({
  name: "AICG3D.CSR.SecondPass",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;
    ensureStyle();
    const original = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = original?.apply(this, args);
      createPanel(this);
      return result;
    };
    const originalConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (...args) {
      const result = originalConfigure?.apply(this, args);
      setTimeout(() => {
        if (!this._csrSecondUi) return;
        syncControls(this, this._csrSecondUi);
        syncSize(this, this._csrSecondUi);
        const state = STATE.get(String(this.id));
        if (state) updatePreview(this, this._csrSecondUi, state);
      }, 0);
      return result;
    };
  },
});
