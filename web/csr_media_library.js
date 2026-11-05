import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "CSRMediaLibrary";
const STYLE_ID = "aicg3d-csr-media-library-style";
const DEFAULT_ROWS = [{ start: 0, end: 10 }];
const ASSET_SLOTS = [
  ["character_1", "替换人物 1"],
  ["character_2", "替换人物 2"],
  ["character_3", "替换人物 3"],
  ["character_4", "替换人物 4"],
  ["background", "背景替换"],
  ["reference", "参考 / 首帧"],
];
const CSS = `
.csr-lib { display:flex; flex-direction:column; gap:8px; width:100%; padding:8px 2px; color:var(--fg-color,#ddd); }
.csr-lib-head { display:flex; align-items:center; gap:8px; }
.csr-lib-title { color:#edf3fc; font-size:13px; font-weight:650; }
.csr-lib-tag { margin-left:auto; border:1px solid #40516c; border-radius:999px; padding:2px 7px; font-size:10px; color:#9cb0cf; }
.csr-lib-video { position:relative; min-height:112px; border:1px dashed #53617a; border-radius:7px; background:#161b23; overflow:hidden; cursor:pointer; }
.csr-lib-video video { width:100%; height:150px; object-fit:contain; background:#090b0f; display:block; }
.csr-lib-video-empty { min-height:112px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:5px; color:#8492a8; font-size:11px; }
.csr-lib-video-empty strong { color:#e2eaf6; font-size:12px; font-weight:550; }
.csr-lib-bar { display:flex; align-items:center; gap:7px; font-size:10px; color:#9eabc0; }
.csr-lib-bar .name { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.csr-lib-btn { height:25px; border:1px solid #455268; border-radius:5px; background:#232a35; color:#dbe6f5; padding:0 8px; cursor:pointer; font-size:10px; }
.csr-lib-btn:hover { border-color:#7094ca; }
.csr-lib-assets { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
.csr-binding { display:flex; flex-direction:column; gap:3px; font-size:10px; color:#96a5bb; }
.csr-binding textarea { width:100%; min-height:45px; resize:vertical; border:1px solid #3e4a5f; border-radius:6px; background:#151a21; color:#dce6f4; padding:6px; font-size:10px; }
.csr-asset { min-width:0; border:1px solid #343e4c; border-radius:7px; background:#1e242d; overflow:hidden; }
.csr-asset-top { display:flex; align-items:center; gap:6px; padding:5px 7px; font-size:10px; color:#a9b7cb; }
.csr-asset-top .x { margin-left:auto; color:#9aa8bc; cursor:pointer; border:0; background:transparent; }
.csr-asset-preview { height:104px; background:#0d1116; display:grid; place-items:center; color:#6f7d92; font-size:10px; cursor:pointer; }
.csr-asset-preview img { width:100%; height:100%; object-fit:contain; display:block; }
.csr-lib-crop { display:flex; flex-direction:column; gap:7px; padding:9px; border:1px solid #354253; border-radius:7px; background:#1b222c; }
.csr-lib-crop-head { display:flex; align-items:center; gap:7px; font-size:11px; color:#dbe7f6; }
.csr-lib-crop-head .hint { margin-left:auto; color:#8fa1b9; font-size:10px; }
.csr-lib-crop-row { display:grid; grid-template-columns:54px minmax(0,1fr) 112px; gap:7px; align-items:center; font-size:10px; color:#9eabc0; }
.csr-lib-crop-row input[type=number] { width:100%; height:26px; border:1px solid #455268; border-radius:5px; background:#121820; color:#edf4fe; padding:0 6px; text-align:center; }
.csr-lib-crop-along { display:flex; align-items:center; gap:5px; }
.csr-lib-crop-along input[type=range] { flex:1; min-width:0; accent-color:#5d8fd8; }
.csr-lib-crop-presets { display:flex; align-items:center; gap:5px; flex-wrap:wrap; }
.csr-lib-crop-presets .csr-lib-btn { height:23px; }
.csr-lib-crop-readout { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#9fb3cd; font-size:10px; text-align:right; }
.csr-lib-tools { display:flex; align-items:center; gap:6px; flex-wrap:wrap; font-size:10px; color:#94a3b8; }
.csr-lib-tools input { width:45px; height:25px; border:1px solid #455268; border-radius:5px; background:#151a21; color:#e6eef9; text-align:center; }
.csr-lib-rows { display:flex; flex-direction:column; gap:5px; }
.csr-lib-row { display:grid; grid-template-columns:50px 1fr 14px 1fr 25px; gap:5px; align-items:center; border:1px solid #343e4c; border-radius:6px; padding:5px; background:#20252e; }
.csr-lib-row input { width:100%; min-width:0; height:25px; border:1px solid #455268; border-radius:5px; background:#131820; color:#edf4fe; padding:0 5px; }
.csr-lib-row .idx { color:#91a5c2; font-size:10px; }
.csr-lib-row .arrow { color:#72819a; text-align:center; }
.csr-lib-status { min-height:15px; color:#8f9eb3; font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.csr-lib-status.error { color:#ff8f8f; }
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

function parseJson(value, fallback) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function readState(node) {
  const parsed = parseJson(node._csrStateWidget?.value, {});
  const state = {};
  for (const [key] of ASSET_SLOTS) {
    const entry = parsed?.[key];
    state[key] = { file: typeof entry === "string" ? entry : String(entry?.file || "") };
  }
  const video = parsed?.video;
  state.video = { file: typeof video === "string" ? video : String(video?.file || "") };
  return state;
}

function setWidget(node, widgetNode, value) {
  if (!widgetNode) return;
  widgetNode.value = value;
  widgetNode.callback?.(value);
  node.setDirtyCanvas?.(true, true);
  node.graph?.setDirtyCanvas?.(true, true);
}

function commitState(node) {
  setWidget(node, node._csrStateWidget, JSON.stringify(node._csrState));
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

function commitRows(node) {
  setWidget(node, node._csrRangeWidget, JSON.stringify(node._csrRows));
  renderRows(node);
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function formatTime(value) {
  const seconds = Math.max(0, Number(value) || 0);
  return `${seconds.toFixed(3).replace(/\.?0+$/, "")}s`;
}

function targetWindow(node) {
  const sourceDuration = Math.max(0, Number(node._csrInfo?.duration || 0));
  const first = node._csrRows?.[0];
  const last = node._csrRows?.at(-1);
  const start = clamp(Number(first?.start || 0), 0, sourceDuration || Number.MAX_SAFE_INTEGER);
  const end = clamp(Number(last?.end || start), start, sourceDuration || Number.MAX_SAFE_INTEGER);
  return { start, end, duration: Math.max(0, end - start), sourceDuration };
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
  const length = Math.min(10, Math.max(0.1, Number(sourceDuration) || 0.1));
  return [{ start: 0, end: length }];
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
    ? `目标段 ${formatTime(windowInfo.start)} → ${formatTime(windowInfo.end)} · 时长 ${formatTime(windowInfo.duration)}`
    : "上传视频后即可用滑块移动目标段";
  for (const button of node._csrCropPresets || []) button.disabled = !hasVideo || Number(button.dataset.seconds) > sourceDuration;
}

function renderRows(node) {
  if (!node._csrRowsBox) return;
  node._csrRowsBox.replaceChildren();
  const duration = Number(node._csrInfo?.duration || 0);
  const error = validateRows(node._csrRows, duration);
  const window = targetWindow(node);
  node._csrRowsStatus.textContent = error || `${node._csrRows.length} 段 · 目标 ${formatTime(window.start)}-${formatTime(window.end)} · 严格首尾相接`;
  node._csrRowsStatus.classList.toggle("error", Boolean(error));
  node._csrRows.forEach((row, index) => {
    const line = el("div", "csr-lib-row");
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
    const remove = el("button", "csr-lib-btn", "×");
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

async function uploadFile(node, file, kind) {
  if (!file) return;
  const form = new FormData();
  form.append("image", file);
  form.append("type", "input");
  form.append("subfolder", "AICG3D-CSR/Media");
  try {
    const response = await api.fetchApi("/upload/image", { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `上传失败 (${response.status})`);
    const path = [payload.subfolder, payload.name].filter(Boolean).join("/");
    if (kind === "video") {
      node._csrResetTarget = true;
      node._csrState.video = { file: path };
      commitState(node);
      setWidget(node, node._csrVideoWidget, path);
      await loadVideo(node, path);
    } else {
      node._csrState[kind] = { file: path };
      commitState(node);
      renderAssets(node);
    }
  } catch (error) {
    node._csrStatus.textContent = String(error?.message || error);
    node._csrStatus.classList.add("error");
  }
}

async function loadVideo(node, file) {
  if (!file) return;
  try {
    const response = await api.fetchApi(`/aicg3d_csr/video_info?file=${encodeURIComponent(file)}`);
    const info = await response.json();
    if (!response.ok || info.error) throw new Error(info.error || "读取视频失败");
    node._csrInfo = info;
    node._csrVideo.src = videoUrl(file);
    node._csrVideo.hidden = false;
    node._csrVideoEmpty.hidden = true;
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
    node._csrStatus.classList.add("error");
  }
}

function renderAssets(node) {
  for (const [key] of ASSET_SLOTS) {
    const refs = node._assetRefs[key];
    const file = node._csrState[key]?.file || "";
    const url = file ? videoUrl(file) : "";
    refs.preview.replaceChildren();
    refs.preview.append(refs.input);
    if (url) {
      const image = el("img");
      image.src = url;
      image.alt = refs.label;
      refs.preview.append(image);
      refs.remove.hidden = false;
    } else {
      refs.preview.append(el("span", "", "点击上传"));
      refs.remove.hidden = true;
    }
  }
  const count = ASSET_SLOTS.filter(([key]) => node._csrState[key]?.file).length;
  node._assetCount.textContent = `素材资源 ${count}/${ASSET_SLOTS.length}`;
}

function createPanel(node) {
  ensureStyle();
  const root = el("div", "csr-lib");
  const head = el("div", "csr-lib-head");
  head.append(el("span", "csr-lib-title", "MiniMax H3 Aicg资源库"), el("span", "csr-lib-tag", "CSR 独立版"));
  root.append(head);

  const videoBox = el("div", "csr-lib-video");
  const videoEmpty = el("div", "csr-lib-video-empty");
  videoEmpty.append(el("strong", "", "上传源视频"), el("span", "", "MP4 / MOV / MKV / WEBM"));
  const video = el("video");
  video.controls = true;
  video.muted = true;
  video.playsInline = true;
  video.hidden = true;
  videoBox.append(videoEmpty, video);
  root.append(videoBox);

  const videoBar = el("div", "csr-lib-bar");
  const videoName = el("span", "name", "未选择源视频");
  const videoUpload = el("button", "csr-lib-btn", "上传视频");
  videoBar.append(videoName, videoUpload);
  root.append(videoBar);
  const audio = el("div", "csr-lib-status", "音轨：等待源视频");
  root.append(audio);

  const crop = el("div", "csr-lib-crop");
  const cropHead = el("div", "csr-lib-crop-head");
  cropHead.append(el("span", "", "目标裁剪"), el("span", "hint", "先设时长，再移动目标段"));
  const lengthRow = el("label", "csr-lib-crop-row");
  const durationInput = el("input");
  durationInput.type = "number";
  durationInput.min = "0.1";
  durationInput.step = "0.1";
  lengthRow.append(el("span", "", "目标时长"), durationInput, el("span", "", "秒"));
  const moveRow = el("div", "csr-lib-crop-row");
  const startSlider = el("input");
  startSlider.type = "range";
  const cropReadout = el("span", "csr-lib-crop-readout", "等待视频");
  moveRow.append(el("span", "", "目标位置"), startSlider, cropReadout);
  const presetRow = el("div", "csr-lib-crop-presets");
  presetRow.append(el("span", "", "快捷时长"));
  const cropPresets = [];
  for (const seconds of [5, 10, 15]) {
    const button = el("button", "csr-lib-btn", `${seconds} 秒`);
    button.dataset.seconds = String(seconds);
    button.onclick = (event) => {
      event.stopPropagation();
      applyTargetLength(node, seconds);
    };
    cropPresets.push(button);
    presetRow.append(button);
  }
  const fullButton = el("button", "csr-lib-btn", "整段");
  fullButton.onclick = (event) => {
    event.stopPropagation();
    applyTargetLength(node, Number(node._csrInfo?.duration || 0));
  };
  presetRow.append(fullButton);
  crop.append(cropHead, lengthRow, moveRow, presetRow);
  root.append(crop);
  durationInput.onchange = () => applyTargetLength(node, Number(durationInput.value));
  startSlider.oninput = () => moveTargetWindow(node, Number(startSlider.value));

  const assetHead = el("div", "csr-lib-head");
  const assetCount = el("span", "csr-lib-title", "素材资源 0");
  assetHead.append(assetCount);
  root.append(assetHead);
  const assets = el("div", "csr-lib-assets");
  root.append(assets);

  const bindingBox = el("label", "csr-binding");
  bindingBox.append(el("span", "", "人物绑定"));
  const bindingInput = el("textarea");
  bindingInput.value = String(widget(node, "character_bindings")?.value || "");
  bindingInput.onchange = () => setWidget(node, widget(node, "character_bindings"), bindingInput.value);
  bindingBox.append(bindingInput);
  root.append(bindingBox);

  const tools = el("div", "csr-lib-tools");
  const countInput = el("input");
  countInput.type = "number";
  countInput.min = "1";
  countInput.max = "200";
  countInput.value = "3";
  const equalButton = el("button", "csr-lib-btn", "均分");
  const h3Button = el("button", "csr-lib-btn", "按3.75秒");
  const addButton = el("button", "csr-lib-btn", "添加分段");
  tools.append(el("span", "", "均分"), countInput, equalButton, h3Button, addButton);
  root.append(tools);
  const rowsBox = el("div", "csr-lib-rows");
  const rowsStatus = el("div", "csr-lib-status", "");
  root.append(rowsBox, rowsStatus);
  const status = el("div", "csr-lib-status", "");
  root.append(status);

  const videoFileInput = document.createElement("input");
  videoFileInput.type = "file";
  videoFileInput.accept = "video/*,.mp4,.mov,.mkv,.webm,.avi,.m4v";
  videoFileInput.hidden = true;
  root.append(videoFileInput);

  Object.assign(node, {
    _csrRoot: root,
    _csrVideo: video,
    _csrVideoEmpty: videoEmpty,
    _csrVideoName: videoName,
    _csrAudio: audio,
    _csrCropDuration: durationInput,
    _csrCropStart: startSlider,
    _csrCropReadout: cropReadout,
    _csrCropPresets: cropPresets,
    _csrRowsBox: rowsBox,
    _csrRowsStatus: rowsStatus,
    _csrStatus: status,
    _assetCount: assetCount,
    _assetRefs: {},
    _csrStateWidget: widget(node, "media_state"),
    _csrRangeWidget: widget(node, "segment_ranges"),
    _csrVideoWidget: null,
  });
  node._csrRows = parseRows(node._csrRangeWidget?.value);
  node._csrState = readState(node);
  if (node._csrStateWidget) node._csrStateWidget.computeSize = () => [0, -4];
  if (node._csrRangeWidget) node._csrRangeWidget.computeSize = () => [0, -4];
  const bindings = widget(node, "character_bindings");
  if (bindings) bindings.computeSize = () => [0, -4];

  for (const [key, label] of ASSET_SLOTS) {
    const card = el("div", "csr-asset");
    const top = el("div", "csr-asset-top");
    const remove = el("button", "x", "×");
    remove.title = `清除${label}`;
    top.append(el("span", "", label), remove);
    const preview = el("div", "csr-asset-preview");
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.hidden = true;
    preview.onclick = () => input.click();
    input.onchange = () => uploadFile(node, input.files?.[0], key);
    remove.onclick = () => {
      node._csrState[key] = { file: "" };
      commitState(node);
      renderAssets(node);
    };
    preview.append(input);
    card.append(top, preview);
    assets.append(card);
    node._assetRefs[key] = { preview, remove, label, input };
  }

  const chooseVideo = () => videoFileInput.click();
  videoBox.onclick = chooseVideo;
  videoUpload.onclick = chooseVideo;
  videoFileInput.onchange = () => uploadFile(node, videoFileInput.files?.[0], "video");
  videoBox.ondragover = (event) => event.preventDefault();
  videoBox.ondrop = (event) => {
    event.preventDefault();
    uploadFile(node, event.dataTransfer?.files?.[0], "video");
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
  node.addDOMWidget("csr_media_library_panel", "AICG3D_CSR_MEDIA_LIBRARY", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 880 + node._csrRows.length * 34,
    getMaxHeight: () => 1600,
  });
  renderAssets(node);
  renderRows(node);
  if (node._csrState.video?.file) loadVideo(node, node._csrState.video.file);
  setTimeout(() => node.setSize?.([Math.max(540, node.size?.[0] || 540), Math.max(1220, node.size?.[1] || 1220)]), 0);
}

app.registerExtension({
  name: "AICG3D.CSR.MediaLibrary",
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
        if (!this._csrStateWidget) return;
        this._csrState = readState(this);
        this._csrRows = parseRows(this._csrRangeWidget?.value);
        renderAssets(this);
        renderRows(this);
        if (this._csrState.video?.file) loadVideo(this, this._csrState.video.file);
      }, 0);
      return result;
    };
  },
});
