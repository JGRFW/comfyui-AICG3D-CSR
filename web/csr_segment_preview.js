import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "CSRSegmentReplace";
const EVENT = "aicg3d_csr_progress";
const STYLE_ID = "aicg3d-csr-segment-preview-style";
const STATE = new Map();
let listenerInstalled = false;

const CSS = `
.csr-live { display:flex; flex-direction:column; gap:7px; width:100%; padding:8px 2px 4px; color:var(--fg-color,#ddd); }
.csr-live-head { display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:12px; }
.csr-live-title { font-weight:600; color:#eef3fb; }
.csr-live-badge { border:1px solid #3f4b60; border-radius:999px; padding:2px 7px; color:#aebbd0; font-size:10px; white-space:nowrap; }
.csr-live-badge.sampling { border-color:#477bc2; color:#8eb8f1; }
.csr-live-badge.ok { border-color:#3e8c67; color:#8bd5ad; }
.csr-live-badge.error { border-color:#a84d4d; color:#ff9b9b; }
.csr-live-track { height:8px; border-radius:999px; background:#2a303a; overflow:hidden; }
.csr-live-fill { width:0%; height:100%; border-radius:999px; background:linear-gradient(90deg,#3d7ae8,#54b8d8); transition:width .22s ease; }
.csr-live-stats { display:grid; grid-template-columns:1fr 1fr; gap:4px 10px; font-size:10px; color:#95a3b8; }
.csr-live-stats b { color:#dce6f5; font-weight:600; }
.csr-live-frame { position:relative; aspect-ratio:16/9; min-height:150px; border:1px solid #343e4e; border-radius:7px; overflow:hidden; background:#090c11; }
.csr-live-frame img, .csr-live-frame video { display:block; width:100%; height:100%; object-fit:contain; background:#090c11; }
.csr-live-frame [hidden] { display:none !important; }
.csr-live-empty { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:5px; color:#748197; font-size:11px; }
.csr-live-empty strong { color:#aebacd; font-size:12px; font-weight:500; }
.csr-live-segment { min-height:16px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#8f9eb4; font-size:10px; }
.csr-tag-row { display:flex; align-items:center; gap:7px; padding:7px 8px; border:1px solid #354253; border-radius:6px; background:#1b222c; }
.csr-tag-row label { color:#9eabc0; font-size:10px; }
.csr-tag-row select { flex:1; min-width:0; height:27px; border:1px solid #455268; border-radius:5px; background:#121820; color:#edf4fe; padding:0 6px; font-size:10px; }
.csr-tag-row button { height:27px; border:1px solid #455268; border-radius:5px; background:#232a35; color:#dbe6f5; padding:0 9px; cursor:pointer; font-size:10px; }
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

const TAG_TEMPLATES = {
  "人物替换": "仅替换视频中的目标人物。人物身份、脸型、五官、发型、身体比例和服装严格来自对应人物参考图；保持原视频的背景、镜头运动、人物站位、身体动作、口型、互动节奏、光线和时长不变。不增加原视频没有的人物或动作。",
  "背景/场景替换": "仅替换视频中的背景和环境，所有人物保持不变。背景整体替换为背景参考图中的完整环境，继承空间结构、墙面、地面、家具、陈设、材质、颜色和光照；删除原视频旧背景，不把背景参考中的人物、文字或水印带入成片。保持人物身份、服装、动作、站位、镜头和时长不变。",
  "物品/产品替换": "仅替换视频中指定的物品或产品，人物保持不变。物品的轮廓、比例、颜色、材质、结构、LOGO 和细节严格来自对应物品参考图；保持原人物身份、脸部、发型、服装、手部姿势、动作、镜头、背景和时长不变。物品必须自然贴合原握持位置、遮挡关系和接触阴影，避免漂浮、穿模、变形和闪烁。",
  "人物 + 背景": "同时替换人物和背景。人物身份、脸型、发型、身体比例和服装来自对应人物参考图；背景整体替换为背景参考图中的完整环境，包括空间结构、家具、材质、颜色和光照。保持原视频镜头、人物站位、动作、口型、互动节奏和时长不变。人物与新背景的透视、比例、光照和接触阴影自然一致，不引入背景参考中的人物、文字、水印或边框。",
  "人物 + 物品": "同时替换人物和指定物品/产品。人物外观严格来自人物参考图，物品轮廓、比例、颜色、材质、结构和 LOGO 严格来自物品参考图。保持原视频背景、镜头、人物动作、手部姿势、口型、站位和时长不变。物品必须自然贴合手部握持、遮挡和接触阴影，不改变未被指定替换的内容。",
  "人物 + 背景 + 物品": "同时替换人物、背景和指定物品/产品。人物身份与服装来自人物参考图，环境来自背景参考图，物品外观与材质来自物品参考图。保持原视频镜头、动作、口型、站位、互动节奏和时长不变。人物与新背景的透视、光照和接触阴影自然一致，物品自然贴合手部姿势和遮挡关系，不引入参考图中无关的人物、文字、水印或物体。",
};

function widget(node, name) {
  return node.widgets?.find((item) => item.name === name);
}

function setWidgetValue(node, name, value) {
  const target = widget(node, name);
  if (!target) return;
  target.value = value;
  target.callback?.(value);
  node.setDirtyCanvas?.(true, true);
  node.graph?.setDirtyCanvas?.(true, true);
}

function graphs() {
  const found = [];
  for (const graph of [app.graph, app.canvas?.graph, app.rootGraph]) {
    if (graph && !found.includes(graph)) found.push(graph);
  }
  return found;
}

function findNode(key) {
  for (const graph of graphs()) {
    for (const node of graph?._nodes || []) {
      if (String(node?.id) === String(key)) return node;
    }
  }
  return null;
}

function clock(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function phaseInfo(detail) {
  if (detail.done && detail.ok === false) return { label: "运行出错", cls: "error" };
  if (detail.phase === "complete") return { label: "全部完成", cls: "ok" };
  if (detail.phase === "segment_saved") return { label: "分段已保存", cls: "ok" };
  if (detail.phase === "resumed") return { label: "断点已恢复", cls: "ok" };
  if (detail.phase === "sampling") return { label: "正在采样", cls: "sampling" };
  if (detail.phase === "decoding") return { label: "解码画面", cls: "sampling" };
  if (detail.phase === "preparing") return { label: "准备分段", cls: "sampling" };
  if (detail.phase === "start") return { label: "开始运行", cls: "sampling" };
  return { label: "等待运行", cls: "" };
}

function thumbnailUrl(file, subfolder) {
  return `/view?filename=${encodeURIComponent(file)}&subfolder=${encodeURIComponent(subfolder || "")}&type=output&t=${Date.now()}`;
}

function updatePanel(node, detail) {
  if (!node?._csrLive) return;
  const ui = node._csrLive;
  const percent = detail.done && detail.ok !== false
    ? 100
    : Math.max(0, Math.min(100, Number(detail.overall || 0) * 100));
  ui.fill.style.width = `${percent.toFixed(2)}%`;
  const info = phaseInfo(detail);
  ui.badge.textContent = info.label;
  ui.badge.className = `csr-live-badge ${info.cls}`.trim();
  ui.segment.textContent = `第 ${detail.segment_number || 0}/${detail.total_segments || 0} 段`;
  const fps = 24;
  const start = (Number(detail.segment_start) || 0) / fps;
  const end = (Number(detail.segment_end) || 0) / fps;
  ui.range.textContent = `区间 ${start.toFixed(3)}–${end.toFixed(3)}s`;
  ui.steps.textContent = `采样 ${Number(detail.step) || 0}/${Number(detail.steps) || 0}`;
  ui.elapsed.textContent = `已用 ${clock(detail.elapsed)}`;
  ui.eta.textContent = detail.eta == null ? "剩余 --:--" : `剩余约 ${clock(detail.eta)}`;
  ui.file.textContent = detail.segment_file ? `已保存 ${detail.segment_file}` : "等待当前分段完成";

  if (detail.preview_jpeg) {
    const jpegPrefix = ["data:", "image/jpeg", ";base64,"].join("");
    ui.image.src = jpegPrefix + detail.preview_jpeg;
    ui.image.hidden = false;
    ui.video.hidden = true;
    ui.video.pause?.();
    ui.empty.hidden = true;
  }
  if (detail.segment_file) {
    ui.video.src = thumbnailUrl(detail.segment_file, detail.segment_subfolder);
    ui.video.hidden = false;
    ui.image.hidden = true;
    ui.empty.hidden = true;
    ui.video.play?.().catch(() => {});
  }
  if (detail.phase === "start") {
    ui.image.hidden = true;
    ui.video.hidden = true;
    ui.video.removeAttribute("src");
    ui.empty.hidden = false;
  }
  if (detail.done && detail.ok === false) {
    ui.file.textContent = detail.error ? `错误：${detail.error}` : "运行失败";
  }
  node.setDirtyCanvas?.(true, true);
}

function installListener() {
  if (listenerInstalled) return;
  listenerInstalled = true;
  api.addEventListener(EVENT, (event) => {
    const detail = event?.detail;
    if (!detail?.node_id) return;
    const key = String(detail.node_id);
    STATE.set(key, { ...detail, receivedAt: Date.now() });
    updatePanel(findNode(key), detail);
  });
}

function createPanel(node) {
  ensureStyle();
  installListener();
  const root = el("div", "csr-live");
  const tagWidget = widget(node, "replacement_tags");
  const tagRow = el("div", "csr-tag-row");
  tagRow.append(el("label", "", "替换标签"));
  const tagSelect = el("select");
  for (const tag of ["自定义", ...Object.keys(TAG_TEMPLATES)]) tagSelect.append(new Option(tag, tag));
  tagSelect.value = String(tagWidget?.value || "自定义");
  const applyTag = el("button", "", "应用模板");
  applyTag.type = "button";
  tagRow.append(tagSelect, applyTag);
  const syncTag = () => {
    const value = String(widget(node, "replacement_tags")?.value || "自定义");
    if (![...tagSelect.options].some((item) => item.value === value)) tagSelect.append(new Option(value, value));
    tagSelect.value = value;
  };
  applyTag.onclick = (event) => {
    event.stopPropagation();
    setWidgetValue(node, "replacement_tags", tagSelect.value);
    const template = TAG_TEMPLATES[tagSelect.value];
    if (template) setWidgetValue(node, "description", template);
  };
  tagSelect.onchange = () => setWidgetValue(node, "replacement_tags", tagSelect.value);
  if (tagWidget) {
    tagWidget.type = "hidden";
    tagWidget.computeSize = () => [0, -4];
  }
  const head = el("div", "csr-live-head");
  const title = el("span", "csr-live-title", "实时分段预览");
  const badge = el("span", "csr-live-badge", "等待运行");
  head.append(title, badge);

  const track = el("div", "csr-live-track");
  const fill = el("div", "csr-live-fill");
  track.append(fill);

  const segment = el("div", "", "第 0/0 段");
  const range = el("div", "", "区间 --");
  const steps = el("div", "", "采样 0/0");
  const elapsed = el("div", "", "已用 00:00");
  const eta = el("div", "", "剩余 --:--");
  const stats = el("div", "csr-live-stats");
  stats.append(segment, range, steps, elapsed, eta);

  const frame = el("div", "csr-live-frame");
  const empty = el("div", "csr-live-empty");
  empty.append(el("strong", "", "等待分段画面"), el("span", "", "采样预览会在这里实时刷新"));
  const image = el("img");
  image.hidden = true;
  image.alt = "CSR live preview";
  const video = el("video");
  video.hidden = true;
  video.controls = true;
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  frame.append(empty, image, video);

  const file = el("div", "csr-live-segment", "等待当前分段完成");
  root.append(tagRow, head, track, stats, frame, file);
  root.onpointerdown = root.onmousedown = root.ontouchstart = (event) => event.stopPropagation();

  node._csrLive = { root, badge, fill, segment, range, steps, elapsed, eta, frame, empty, image, video, file };
  node._csrLive = { root, tagSelect, syncTag, badge, fill, segment, range, steps, elapsed, eta, frame, empty, image, video, file };
  node.addDOMWidget("csr_segment_live_preview", "AICG3D_CSR_LIVE", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 300,
    getMaxHeight: () => 440,
  });
  setTimeout(() => {
    if (!node.size) return;
    node.setSize?.([Math.max(520, node.size[0]), Math.max(850, node.size[1])]);
    node.setDirtyCanvas?.(true, true);
  }, 0);
}

app.registerExtension({
  name: "AICG3D.CSR.SegmentLivePreview",
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
        this._csrLive?.syncTag?.();
        const state = STATE.get(String(this.id));
        if (state) updatePanel(this, state);
      }, 0);
      return result;
    };
  },
});
