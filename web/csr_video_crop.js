import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "CSRVideoCrop";
const STYLE_ID = "aicg3d-csr-video-crop-style";
const DEFAULT_ROWS = [{ start: 0, end: 10 }];
const RESOLUTION_OPTIONS = ["360P", "480P", "540P", "720P", "1080P", "自定义"];
const ASPECT_OPTIONS = ["跟随源视频", "16:9", "16:10", "9:16", "1:1", "4:3", "3:4", "21:9"];
const ASPECT_VALUES = { "16:9": 16 / 9, "16:10": 16 / 10, "9:16": 9 / 16, "1:1": 1, "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9 };
const CSS = `
.csr-vc { display:flex; flex-direction:column; gap:8px; width:100%; padding:8px 2px; color:var(--fg-color,#ddd); }
.csr-vc-head { display:flex; align-items:center; gap:8px; }
.csr-vc-title { color:#edf3fc; font-size:13px; font-weight:650; }
.csr-vc-tag { margin-left:auto; border:1px solid #40516c; border-radius:999px; padding:2px 7px; font-size:10px; color:#9cb0cf; }
.csr-vc-video { position:relative; height:120px; min-height:120px; border:1px dashed #53617a; border-radius:7px; background:#161b23; overflow:hidden; cursor:pointer; }
.csr-vc-video.has-video { border-style:solid; border-color:#40516c; cursor:default; }
.csr-vc-video video { width:100%; height:100%; object-fit:contain; background:#090b0f; display:block; }
.csr-vc-empty { min-height:120px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:5px; color:#8492a8; font-size:11px; }
.csr-vc-empty strong { color:#e2eaf6; font-size:12px; font-weight:550; }
.csr-vc-bar { display:flex; align-items:center; gap:7px; font-size:10px; color:#9eabc0; }
.csr-vc-bar .name { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.csr-vc-btn { height:25px; border:1px solid #455268; border-radius:5px; background:#232a35; color:#dbe6f5; padding:0 8px; cursor:pointer; font-size:10px; }
.csr-vc-btn:hover { border-color:#7094ca; }
.csr-vc-btn:disabled { opacity:.45; cursor:default; }
.csr-vc-crop { display:flex; flex-direction:column; gap:7px; padding:9px; border:1px solid #354253; border-radius:7px; background:#1b222c; }
.csr-vc-crop-head { display:flex; align-items:center; gap:7px; font-size:11px; color:#dbe7f6; }
.csr-vc-crop-head .hint { margin-left:auto; color:#8fa1b9; font-size:10px; }
.csr-vc-crop-row { display:grid; grid-template-columns:54px minmax(0,1fr) 112px; gap:7px; align-items:center; font-size:10px; color:#9eabc0; }
.csr-vc-crop-row input[type=number] { width:100%; height:26px; border:1px solid #455268; border-radius:5px; background:#121820; color:#edf4fe; padding:0 6px; text-align:center; }
.csr-vc-crop-row input[type=range] { min-width:0; accent-color:#5d8fd8; }
.csr-vc-presets { display:flex; align-items:center; gap:5px; flex-wrap:wrap; }
.csr-vc-presets .csr-vc-btn { height:23px; }
.csr-vc-readout { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#9fb3cd; font-size:10px; text-align:right; }
.csr-vc-tools { display:flex; align-items:center; gap:6px; flex-wrap:wrap; font-size:10px; color:#94a3b8; }
.csr-vc-tools input { width:45px; height:25px; border:1px solid #455268; border-radius:5px; background:#151a21; color:#e6eef9; text-align:center; }
.csr-vc-rows { display:flex; flex-direction:column; gap:5px; max-height:272px; overflow:auto; padding-right:3px; }
.csr-vc-row { display:grid; grid-template-columns:50px 1fr 14px 1fr 25px; gap:5px; align-items:center; border:1px solid #343e4c; border-radius:6px; padding:5px; background:#20252e; }
.csr-vc-row input { width:100%; min-width:0; height:25px; border:1px solid #455268; border-radius:5px; background:#131820; color:#edf4fe; padding:0 5px; }
.csr-vc-row .idx { color:#91a5c2; font-size:10px; }
.csr-vc-row .arrow { color:#72819a; text-align:center; }
.csr-vc-status { min-height:15px; color:#8f9eb3; font-size:10px; overflow-wrap:anywhere; white-space:normal; line-height:1.4; }
.csr-vc-status.error { color:#ff8f8f; }
.csr-vc-res { display:flex; flex-direction:column; gap:7px; padding:9px; border:1px solid #354253; border-radius:7px; background:#1b222c; }
.csr-vc-res-head { display:flex; align-items:center; gap:7px; font-size:11px; color:#dbe7f6; }
.csr-vc-res-head .hint { margin-left:auto; color:#8fa1b9; font-size:10px; }
.csr-vc-res-main { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; align-items:end; }
.csr-vc-res-field { display:flex; flex-direction:column; gap:4px; min-width:0; color:#9eabc0; font-size:10px; }
.csr-vc-res-field select, .csr-vc-res-field input { width:100%; height:28px; border:1px solid #455268; border-radius:5px; background:#121820; color:#edf4fe; padding:0 7px; }
.csr-vc-res-custom { display:grid; grid-template-columns:72px minmax(0,1fr); gap:7px; align-items:center; font-size:10px; color:#9eabc0; }
.csr-vc-res-custom[hidden] { display:none; }
.csr-vc-res-size { display:grid; grid-template-columns:minmax(0,1fr) 18px minmax(0,1fr); gap:5px; align-items:center; }
.csr-vc-res-readout { min-height:15px; color:#9fb3cd; font-size:10px; line-height:1.35; }
`;

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const tag = document.createElement("style");
  tag.id = STYLE_ID;
  tag.textContent = CSS;
  document.head.append(tag);
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function widget(node, name) {
  return node.widgets?.find((item) => item.name === name);
}

function hideWidget(widgetNode) {
  if (!widgetNode) return;
  widgetNode.type = "hidden";
  widgetNode.computeSize = () => [0, -4];
  if (widgetNode.inputEl) widgetNode.inputEl.style.display = "none";
  if (widgetNode.element) widgetNode.element.style.display = "none";
}

function parseJson(value, fallback) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function setWidget(node, widgetNode, value) {
  if (!widgetNode) return;
  widgetNode.value = value;
  widgetNode.callback?.(value);
  node.setDirtyCanvas?.(true, true);
  node.graph?.setDirtyCanvas?.(true, true);
}

function setValue(node, name, value) {
  setWidget(node, widget(node, name), value);
}

function readVideoState(node) {
  const parsed = parseJson(node._csrVideoStateWidget?.value, {});
  const video = parsed?.video;
  return { video: { file: typeof video === "string" ? video : String(video?.file || "") } };
}

function commitVideoState(node) {
  setWidget(node, node._csrVideoStateWidget, JSON.stringify(node._csrVideoState));
}

function videoUrl(file) {
  const clean = String(file || "").replace(/\\/g, "/");
  const slash = clean.lastIndexOf("/");
  return `/view?filename=${encodeURIComponent(slash >= 0 ? clean.slice(slash + 1) : clean)}&type=input&subfolder=${encodeURIComponent(slash >= 0 ? clean.slice(0, slash) : "")}`;
}

function parseRows(value) {
  const parsed = parseJson(value, DEFAULT_ROWS);
  if (!Array.isArray(parsed) || !parsed.length) return DEFAULT_ROWS.map((row) => ({ ...row }));
  return parsed.map((row) => ({
    start: Number(Array.isArray(row) ? row[0] : row.start),
    end: Number(Array.isArray(row) ? row[1] : row.end),
  })).filter((row) => Number.isFinite(row.start) && Number.isFinite(row.end) && row.end > row.start);
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function formatTime(value) {
  return `${Math.max(0, Number(value) || 0).toFixed(3).replace(/\.?0+$/, "")}s`;
}

function targetWindow(node) {
  const sourceDuration = Math.max(0, Number(node._csrInfo?.duration || 0));
  const first = node._csrRows?.[0];
  const last = node._csrRows?.at(-1);
  const start = clamp(Number(first?.start || 0), 0, sourceDuration || Number.MAX_SAFE_INTEGER);
  const end = clamp(Number(last?.end || start), start, sourceDuration || Number.MAX_SAFE_INTEGER);
  return { start, end, duration: Math.max(0, end - start), sourceDuration };
}

function validateRows(rows, duration) {
  if (!rows.length) return "至少需要一段";
  const eps = 1 / 48;
  if (rows[0].start < -eps) return "目标段起点不能小于 0";
  for (let i = 0; i < rows.length; i += 1) {
    if (!(rows[i].end > rows[i].start)) return `第 ${i + 1} 段结束必须大于开始`;
    if (duration > 0 && rows[i].end > duration + eps) return `第 ${i + 1} 段超出视频时长`;
    if (i && Math.abs(rows[i].start - rows[i - 1].end) > eps) return "相邻分段必须首尾相接";
  }
  return "";
}

function equalRows(duration, count, start = 0) {
  const safeDuration = Math.max(0, Number(duration) || 0);
  const safeCount = Math.max(1, Math.min(200, Math.floor(Number(count) || 1)));
  const rows = [];
  for (let i = 0; i < safeCount; i += 1) {
    rows.push({
      start: Number(start) + safeDuration * i / safeCount,
      end: Number(start) + safeDuration * (i + 1) / safeCount,
    });
  }
  return rows;
}

function suggestedRows(duration, start = 0) {
  return equalRows(duration, Math.max(1, Math.ceil(Number(duration || 1) / 3.75)), start);
}

function defaultTargetRows(sourceDuration) {
  return [{ start: 0, end: Math.min(10, Math.max(0.1, Number(sourceDuration) || 0.1)) }];
}

function rowInput(value, onChange) {
  const input = el("input");
  input.type = "number";
  input.min = "0";
  input.step = "0.001";
  input.value = Number(value).toFixed(3).replace(/\.?0+$/, "");
  input.onpointerdown = input.onmousedown = input.ontouchstart = (event) => event.stopPropagation();
  input.onchange = () => onChange(Number(input.value));
  return input;
}

function commitRows(node) {
  setWidget(node, node._csrRangeWidget, JSON.stringify(node._csrRows));
  renderRows(node);
}

function applyTargetLength(node, requestedLength) {
  const sourceDuration = Number(node._csrInfo?.duration || 0);
  if (!(sourceDuration > 0)) return;
  const current = targetWindow(node);
  const length = clamp(Number(requestedLength) || 0.1, 0.1, sourceDuration);
  const start = clamp(current.start, 0, Math.max(0, sourceDuration - length));
  node._csrRows = [{ start, end: start + length }];
  commitRows(node);
  if (node._csrVideo) node._csrVideo.currentTime = start;
}

function moveTargetWindow(node, requestedStart) {
  const sourceDuration = Number(node._csrInfo?.duration || 0);
  if (!(sourceDuration > 0) || !node._csrRows.length) return;
  const current = targetWindow(node);
  const start = clamp(Number(requestedStart) || 0, 0, Math.max(0, sourceDuration - current.duration));
  const delta = start - current.start;
  node._csrRows = node._csrRows.map((row) => ({ start: row.start + delta, end: row.end + delta }));
  commitRows(node);
  if (node._csrVideo) node._csrVideo.currentTime = start;
}

function renderCrop(node) {
  if (!node._csrCropDuration || !node._csrCropStart || !node._csrCropReadout) return;
  const windowInfo = targetWindow(node);
  const sourceDuration = windowInfo.sourceDuration;
  const hasVideo = sourceDuration > 0;
  node._csrCropDuration.disabled = !hasVideo;
  node._csrCropStart.disabled = !hasVideo;
  node._csrCropDuration.max = String(Math.max(0.1, sourceDuration || 0.1));
  node._csrCropDuration.value = Number(windowInfo.duration || 0.1).toFixed(3).replace(/\.?0+$/, "");
  node._csrCropStart.min = "0";
  node._csrCropStart.max = String(Math.max(0, sourceDuration - windowInfo.duration));
  node._csrCropStart.step = "0.001";
  node._csrCropStart.value = String(windowInfo.start);
  node._csrCropReadout.textContent = hasVideo
    ? `${formatTime(windowInfo.start)} → ${formatTime(windowInfo.end)} · ${formatTime(windowInfo.duration)}`
    : "上传视频后可移动目标段";
  for (const button of node._csrCropPresets || []) button.disabled = !hasVideo || Number(button.dataset.seconds) > sourceDuration;
}

function evenRound(value) {
  return Math.max(2, Math.floor(Number(value) / 2 + 0.5) * 2);
}

function resolutionPreview(node) {
  const info = node._csrInfo || {};
  const sourceWidth = Number(info.width || 0);
  const sourceHeight = Number(info.height || 0);
  let preset = String(node._csrResolutionSelect?.value || node._csrResolutionPreset?.value || "540P");
  if (preset === "默认（短边）") preset = "540P";
  const aspectName = String(node._csrAspectSelect?.value || "16:9");
  const aspect = ASPECT_VALUES[aspectName];
  let width = 0;
  let height = 0;
  if (preset === "自定义") {
    width = Math.max(0, Number(node._csrCustomWidth?.value || 0));
    height = Math.max(0, Number(node._csrCustomHeight?.value || 0));
    if (sourceWidth > 0 && sourceHeight > 0 && width > 0 && height <= 0) height = Math.round(width * sourceHeight / sourceWidth);
    if (sourceWidth > 0 && sourceHeight > 0 && height > 0 && width <= 0) width = Math.round(height * sourceWidth / sourceHeight);
  } else {
    const shortEdge = Number(String(preset).replace(/P$/i, "")) || 540;
    if (aspect) {
      if (aspect >= 1) {
        height = shortEdge;
        width = shortEdge * aspect;
      } else {
        width = shortEdge;
        height = shortEdge / aspect;
      }
    } else {
      if (!(sourceWidth > 0) || !(sourceHeight > 0)) return null;
      const scale = shortEdge / Math.min(sourceWidth, sourceHeight);
      width = sourceWidth * scale;
      height = sourceHeight * scale;
    }
  }
  width = evenRound(width);
  height = evenRound(height);
  if (!(width > 0) || !(height > 0)) return null;
  return {
    width,
    height,
    modelWidth: Math.max(32, Math.ceil(width / 32) * 32),
    modelHeight: Math.max(32, Math.ceil(height / 32) * 32),
  };
}

function renderResolution(node) {
  if (!node._csrResolutionSelect || !node._csrResolutionReadout) return;
  const custom = node._csrResolutionSelect.value === "自定义";
  node._csrCustomWidth.disabled = !custom;
  node._csrCustomHeight.disabled = !custom;
  if (node._csrResolutionCustomRow) node._csrResolutionCustomRow.hidden = !custom;
  if (node._csrAspectSelect) node._csrAspectSelect.disabled = custom;
  const preview = resolutionPreview(node);
  node._csrResolutionReadout.textContent = preview
    ? `最终 ${preview.width}×${preview.height} · 模型画布 ${preview.modelWidth}×${preview.modelHeight}（32 像素对齐）`
    : "上传视频后显示实际输出尺寸";
}

function syncResolutionControls(node) {
  if (!node._csrResolutionSelect || !node._csrAspectSelect) return;
  let preset = String(node._csrResolutionPreset?.value || "540P");
  if (!RESOLUTION_OPTIONS.includes(preset)) preset = "540P";
  let aspect = String(node._csrAspectRatioWidget?.value || "16:9");
  if (!ASPECT_OPTIONS.includes(aspect)) aspect = "16:9";
  node._csrResolutionSelect.value = preset;
  node._csrAspectSelect.value = aspect;
  node._csrCustomWidth.value = String(node._csrCustomWidthWidget?.value ?? 0);
  node._csrCustomHeight.value = String(node._csrCustomHeightWidget?.value ?? 0);
  if (node._csrResolutionPreset && node._csrResolutionPreset.value !== preset) setValue(node, "resolution_preset", preset);
  if (node._csrAspectRatioWidget && node._csrAspectRatioWidget.value !== aspect) setValue(node, "aspect_ratio", aspect);
  renderResolution(node);
}

function renderRows(node) {

  if (!node._csrRowsBox) return;
  node._csrRowsBox.replaceChildren();
  const duration = Number(node._csrInfo?.duration || 0);
  const error = validateRows(node._csrRows, duration);
  const windowInfo = targetWindow(node);
  node._csrRowsStatus.textContent = error || `${node._csrRows.length} 段 · 目标 ${formatTime(windowInfo.start)}-${formatTime(windowInfo.end)}`;
  node._csrRowsStatus.classList.toggle("error", Boolean(error));
  node._csrRows.forEach((row, index) => {
    const line = el("div", "csr-vc-row");
    line.append(el("span", "idx", `第 ${index + 1} 段`));
    const start = rowInput(row.start, (value) => {
      row.start = Math.max(0, value);
      if (index) node._csrRows[index - 1].end = row.start;
      commitRows(node);
    });
    const end = rowInput(row.end, (value) => {
      row.end = duration > 0 ? Math.min(duration, value) : value;
      if (index < node._csrRows.length - 1) node._csrRows[index + 1].start = row.end;
      commitRows(node);
    });
    const remove = el("button", "csr-vc-btn", "×");
    remove.onclick = (event) => {
      event.stopPropagation();
      if (node._csrRows.length <= 1) return;
      const removed = node._csrRows.splice(index, 1)[0];
      if (index) node._csrRows[index - 1].end = removed.end;
      commitRows(node);
    };
    line.append(start, el("span", "arrow", "→"), end, remove);
    node._csrRowsBox.append(line);
  });
  renderCrop(node);
}

function syncPanelHeight(node, fallbackHeight = 500) {
  const panel = node._csrPanelWidget;
  if (!panel) return;
  const measured = Math.ceil(node._csrRoot?.scrollHeight || 0);
  const panelHeight = Math.max(fallbackHeight, measured + 12);
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
}

function resizeVideoPreview(node, info) {
  if (!node._csrVideoBox || !(Number(info?.width) > 0) || !(Number(info?.height) > 0)) return;
  const width = Math.max(360, Number(node._csrVideoBox.clientWidth || 0) || (Number(node.size?.[0] || 540) - 20));
  const ideal = width * Number(info.height) / Number(info.width);
  const previewHeight = clamp(ideal, 240, 440);
  node._csrVideoBox.style.height = `${previewHeight}px`;
  const extra = Math.max(0, previewHeight - 120);
  syncPanelHeight(node, 500 + extra);
  node.setDirtyCanvas?.(true, true);
}

async function uploadVideo(node, file) {
  if (!file) return;
  const form = new FormData();
  form.append("image", file);
  form.append("type", "input");
  form.append("subfolder", "AICG3D-CSR/Video");
  try {
    const response = await api.fetchApi("/upload/image", { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `上传失败 (${response.status})`);
    const path = [payload.subfolder, payload.name].filter(Boolean).join("/");
    node._csrResetTarget = true;
    node._csrVideoState.video = { file: path };
    commitVideoState(node);
    await loadVideo(node, path);
  } catch (error) {
    node._csrStatus.textContent = String(error?.message || error);
    node._csrStatus.title = String(error?.message || error);
    node._csrStatus.classList.add("error");
  }
}

async function loadVideo(node, file) {
  if (!file) return;
  try {
    const response = await api.fetchApi(`/aicg3d_csr/video_info?file=${encodeURIComponent(file)}`);
    const info = await response.json();
    if (!response.ok || info.error) throw new Error(info.error || "读取视频失败");
    node._csrStatus.textContent = "";
    node._csrStatus.title = "";
    node._csrStatus.classList.remove("error");
    node._csrInfo = info;
    renderResolution(node);
    node._csrVideo.src = videoUrl(file);
    node._csrVideo.hidden = false;
    node._csrVideoEmpty.hidden = true;
    node._csrVideoEmpty.style.display = "none";
    node._csrVideoBox.classList.add("has-video");
    resizeVideoPreview(node, info);
    node._csrAudio.textContent = info.has_audio
      ? "音轨：已自动分离，分段视频保持静音，最终合并后追加"
      : "音轨：源视频无音频";
    node._csrVideoName.textContent = `${file.split("/").at(-1)} · ${info.width}x${info.height} · ${Number(info.duration).toFixed(3)}s`;
    if (node._csrResetTarget || validateRows(node._csrRows, Number(info.duration || 0))) {
      node._csrRows = defaultTargetRows(Number(info.duration || 0));
    }
    node._csrResetTarget = false;
    commitRows(node);
  } catch (error) {
    node._csrStatus.textContent = String(error?.message || error);
    node._csrStatus.title = String(error?.message || error);
    node._csrStatus.classList.add("error");
  }
}

function createPanel(node) {
  ensureStyle();
  const root = el("div", "csr-vc");
  const head = el("div", "csr-vc-head");
  head.append(el("span", "csr-vc-title", "MiniMax H3 Aicg 视频裁剪"), el("span", "csr-vc-tag", "CSR 独立版"));
  root.append(head);

  const videoBox = el("div", "csr-vc-video");
  const videoEmpty = el("div", "csr-vc-empty");
  videoEmpty.append(el("strong", "", "上传源视频"), el("span", "", "MP4 / MOV / MKV / WEBM"));
  const video = el("video");
  video.controls = true;
  video.muted = true;
  video.playsInline = true;
  video.hidden = true;
  videoBox.append(videoEmpty, video);
  root.append(videoBox);

  const videoBar = el("div", "csr-vc-bar");
  const videoName = el("span", "name", "未选择源视频");
  const videoUpload = el("button", "csr-vc-btn", "上传视频");
  videoBar.append(videoName, videoUpload);
  root.append(videoBar);
  const audio = el("div", "csr-vc-status", "音轨：等待源视频");
  root.append(audio);

  const resolutionBox = el("div", "csr-vc-res");
  const resolutionHead = el("div", "csr-vc-res-head");
  resolutionHead.append(el("span", "", "输出分辨率"), el("span", "hint", "固定短边 + 宽高比"));
  const resolutionSelect = el("select");
  for (const value of RESOLUTION_OPTIONS) resolutionSelect.append(new Option(value, value));
  const aspectSelect = el("select");
  for (const value of ASPECT_OPTIONS) aspectSelect.append(new Option(value, value));
  const presetWidget = widget(node, "resolution_preset");
  const aspectWidget = widget(node, "aspect_ratio");
  const initialPreset = String(presetWidget?.value || "540P");
  resolutionSelect.value = RESOLUTION_OPTIONS.includes(initialPreset) ? initialPreset : "540P";
  const initialAspect = String(aspectWidget?.value || "16:9");
  aspectSelect.value = ASPECT_OPTIONS.includes(initialAspect) ? initialAspect : "16:9";
  if (presetWidget && presetWidget.value !== resolutionSelect.value) presetWidget.value = resolutionSelect.value;
  if (aspectWidget && aspectWidget.value !== aspectSelect.value) aspectWidget.value = aspectSelect.value;
  const resolutionField = el("label", "csr-vc-res-field");
  resolutionField.append(el("span", "", "分辨率"), resolutionSelect);
  const aspectField = el("label", "csr-vc-res-field");
  aspectField.append(el("span", "", "宽高比"), aspectSelect);
  const resolutionMain = el("div", "csr-vc-res-main");
  resolutionMain.append(resolutionField, aspectField);
  const customRow = el("label", "csr-vc-res-custom");
  const sizeBox = el("div", "csr-vc-res-size");
  const customWidth = el("input");
  const customHeight = el("input");
  customWidth.type = customHeight.type = "number";
  customWidth.min = customHeight.min = "0";
  customWidth.step = customHeight.step = "2";
  customWidth.value = String(widget(node, "custom_width")?.value ?? 0);
  customHeight.value = String(widget(node, "custom_height")?.value ?? 0);
  sizeBox.append(customWidth, el("span", "", "×"), customHeight);
  customRow.append(el("span", "", "自定义"), sizeBox);
  customRow.hidden = resolutionSelect.value !== "自定义";
  const resolutionReadout = el("div", "csr-vc-res-readout", "上传视频后显示最终输出和模型画布尺寸");
  resolutionBox.append(resolutionHead, resolutionMain, customRow, resolutionReadout);
  root.append(resolutionBox);
  const updateResolutionMode = () => {
    const custom = resolutionSelect.value === "自定义";
    customWidth.disabled = !custom;
    customHeight.disabled = !custom;
    customRow.hidden = !custom;
    setValue(node, "resolution_preset", resolutionSelect.value);
    renderResolution(node);
  };
  const updateAspect = () => {
    setValue(node, "aspect_ratio", aspectSelect.value);
    renderResolution(node);
  };
  resolutionSelect.oninput = updateResolutionMode;
  resolutionSelect.onchange = updateResolutionMode;
  aspectSelect.oninput = updateAspect;
  aspectSelect.onchange = updateAspect;
  customWidth.onchange = () => {
    setValue(node, "custom_width", Number(customWidth.value) || 0);
    renderResolution(node);
  };
  customHeight.onchange = () => {
    setValue(node, "custom_height", Number(customHeight.value) || 0);
    renderResolution(node);
  };

  const crop = el("div", "csr-vc-crop");
  const cropHead = el("div", "csr-vc-crop-head");
  cropHead.append(el("span", "", "目标裁剪"), el("span", "hint", "先设时长，再移动目标段"));
  const lengthRow = el("label", "csr-vc-crop-row");
  const durationInput = el("input");
  durationInput.type = "number";
  durationInput.min = "0.1";
  durationInput.step = "0.1";
  lengthRow.append(el("span", "", "目标时长"), durationInput, el("span", "", "秒"));
  const moveRow = el("div", "csr-vc-crop-row");
  const startSlider = el("input");
  startSlider.type = "range";
  const cropReadout = el("span", "csr-vc-readout", "等待视频");
  moveRow.append(el("span", "", "目标位置"), startSlider, cropReadout);
  const presetRow = el("div", "csr-vc-presets");
  presetRow.append(el("span", "", "快捷时长"));
  const cropPresets = [];
  for (const seconds of [5, 10, 15]) {
    const button = el("button", "csr-vc-btn", `${seconds} 秒`);
    button.dataset.seconds = String(seconds);
    button.onclick = (event) => {
      event.stopPropagation();
      applyTargetLength(node, seconds);
    };
    cropPresets.push(button);
    presetRow.append(button);
  }
  const fullButton = el("button", "csr-vc-btn", "整段");
  fullButton.onclick = (event) => {
    event.stopPropagation();
    applyTargetLength(node, Number(node._csrInfo?.duration || 0));
  };
  presetRow.append(fullButton);
  crop.append(cropHead, lengthRow, moveRow, presetRow);
  root.append(crop);
  durationInput.onchange = () => applyTargetLength(node, Number(durationInput.value));
  startSlider.oninput = () => moveTargetWindow(node, Number(startSlider.value));

  const tools = el("div", "csr-vc-tools");
  const countInput = el("input");
  countInput.type = "number";
  countInput.min = "1";
  countInput.max = "200";
  countInput.value = "3";
  const equalButton = el("button", "csr-vc-btn", "均分");
  const h3Button = el("button", "csr-vc-btn", "按3.75秒");
  const addButton = el("button", "csr-vc-btn", "添加分段");
  tools.append(el("span", "", "均分"), countInput, equalButton, h3Button, addButton);
  root.append(tools);
  const rowsBox = el("div", "csr-vc-rows");
  const rowsStatus = el("div", "csr-vc-status", "");
  root.append(rowsBox, rowsStatus);
  const status = el("div", "csr-vc-status", "");
  root.append(status);

  const videoFileInput = document.createElement("input");
  videoFileInput.type = "file";
  videoFileInput.accept = "video/*,.mp4,.mov,.mkv,.webm,.avi,.m4v";
  videoFileInput.hidden = true;
  root.append(videoFileInput);

  Object.assign(node, {
    _csrRoot: root,
    _csrVideo: video,
    _csrVideoBox: videoBox,
    _csrVideoEmpty: videoEmpty,
    _csrVideoName: videoName,
    _csrAudio: audio,
    _csrResolutionSelect: resolutionSelect,
    _csrAspectSelect: aspectSelect,
    _csrCustomWidth: customWidth,
    _csrCustomHeight: customHeight,
    _csrResolutionCustomRow: customRow,
    _csrResolutionReadout: resolutionReadout,
    _csrResolutionPreset: presetWidget,
    _csrAspectRatioWidget: aspectWidget,
    _csrCustomWidthWidget: widget(node, "custom_width"),
    _csrCustomHeightWidget: widget(node, "custom_height"),
    _csrCropDuration: durationInput,
    _csrCropStart: startSlider,
    _csrCropReadout: cropReadout,
    _csrCropPresets: cropPresets,
    _csrRowsBox: rowsBox,
    _csrRowsStatus: rowsStatus,
    _csrStatus: status,
    _csrVideoStateWidget: widget(node, "video_state"),
    _csrRangeWidget: widget(node, "segment_ranges"),
  });
  node._csrRows = parseRows(node._csrRangeWidget?.value);
  node._csrVideoState = readVideoState(node);
  hideWidget(node._csrVideoStateWidget);
  hideWidget(node._csrRangeWidget);
  hideWidget(widget(node, "short_edge"));
  hideWidget(node._csrResolutionPreset);
  hideWidget(node._csrAspectRatioWidget);
  hideWidget(node._csrCustomWidthWidget);
  hideWidget(node._csrCustomHeightWidget);

  const chooseVideo = () => videoFileInput.click();
  videoBox.onclick = chooseVideo;
  videoUpload.onclick = chooseVideo;
  videoFileInput.onchange = () => uploadVideo(node, videoFileInput.files?.[0]);
  videoBox.ondragover = (event) => event.preventDefault();
  videoBox.ondrop = (event) => {
    event.preventDefault();
    uploadVideo(node, event.dataTransfer?.files?.[0]);
  };
  equalButton.onclick = () => {
    const windowInfo = targetWindow(node);
    node._csrRows = equalRows(windowInfo.duration, countInput.value, windowInfo.start);
    commitRows(node);
  };
  h3Button.onclick = () => {
    const windowInfo = targetWindow(node);
    node._csrRows = suggestedRows(windowInfo.duration, windowInfo.start);
    countInput.value = String(node._csrRows.length);
    commitRows(node);
  };
  addButton.onclick = () => {
    const last = node._csrRows.at(-1);
    if (!last) return;
    const mid = (last.start + last.end) / 2;
    if (mid - last.start < 0.05 || last.end - mid < 0.05) return;
    const end = last.end;
    last.end = mid;
    node._csrRows.push({ start: mid, end });
    countInput.value = String(node._csrRows.length);
    commitRows(node);
  };

  root.onpointerdown = root.onmousedown = root.ontouchstart = (event) => event.stopPropagation();
  node._csrPanelWidget = node.addDOMWidget("csr_video_crop_panel", "AICG3D_CSR_VIDEO_CROP", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 500,
    getMaxHeight: () => 4096,
  });
  renderRows(node);
  syncResolutionControls(node);
  if (node._csrVideoState.video?.file) loadVideo(node, node._csrVideoState.video.file);
  setTimeout(() => {
    syncPanelHeight(node);
    requestAnimationFrame(() => syncPanelHeight(node));
  }, 0);
}

app.registerExtension({
  name: "AICG3D.CSR.VideoCrop",
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
        if (!this._csrVideoStateWidget) return;
        this._csrVideoState = readVideoState(this);
        this._csrRows = parseRows(this._csrRangeWidget?.value);
        renderRows(this);
        syncResolutionControls(this);
        if (this._csrVideoState.video?.file) loadVideo(this, this._csrVideoState.video.file);
        requestAnimationFrame(() => syncPanelHeight(this));
      }, 0);
      return result;
    };
  },
});
