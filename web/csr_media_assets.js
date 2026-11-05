import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "CSRMediaAssets";
const STYLE_ID = "aicg3d-csr-media-assets-style";
const ASSET_SLOTS = [
  ["character_1", "替换物 1"],
  ["character_2", "替换物 2"],
  ["character_3", "替换物 3"],
  ["character_4", "替换物 4"],
  ["character_5", "替换物 5"],
  ["character_6", "替换物 6"],
  ["character_7", "替换物 7"],
  ["background", "背景替换"],
  ["reference", "参考 / 首帧"],
];
const MIN_CHARACTERS = 2;
const DEFAULT_VISIBLE_CHARACTERS = 2;
const MAX_CHARACTERS = 7;
const CHARACTER_KEYS = Array.from({ length: MAX_CHARACTERS }, (_, index) => `character_${index + 1}`);
const CSS = `
.csr-ma { display:flex; flex-direction:column; gap:8px; width:100%; padding:8px 2px; color:var(--fg-color,#ddd); }
.csr-ma-head { display:flex; align-items:center; gap:8px; }
.csr-ma-title { color:#edf3fc; font-size:13px; font-weight:650; }
.csr-ma-tag { margin-left:auto; border:1px solid #40516c; border-radius:999px; padding:2px 7px; font-size:10px; color:#9cb0cf; }
.csr-ma-slotbar { display:flex; align-items:center; gap:6px; padding:6px 8px; border:1px solid #354253; border-radius:6px; background:#1b222c; color:#9eabc0; font-size:10px; }
.csr-ma-slotbar .spacer { flex:1; }
.csr-ma-slotbar button { width:24px; height:22px; border:1px solid #455268; border-radius:5px; background:#242b36; color:#dbe6f5; cursor:pointer; }
.csr-ma-slotbar button:disabled { opacity:.4; cursor:default; }
.csr-ma-assets { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:7px; }
.csr-ma-card { min-width:0; border:1px solid #343e4c; border-radius:7px; background:#1e242d; overflow:hidden; }
.csr-ma-top { display:flex; align-items:center; gap:6px; padding:5px 7px; font-size:10px; color:#a9b7cb; }
.csr-ma-top .x { margin-left:auto; color:#9aa8bc; cursor:pointer; border:0; background:transparent; }
.csr-ma-top select { height:22px; max-width:78px; border:1px solid #3e4a5f; border-radius:4px; background:#171c24; color:#dce6f4; font-size:9px; padding:0 3px; }
.csr-ma-preview { height:112px; background:#0d1116; display:grid; place-items:center; color:#6f7d92; font-size:10px; cursor:pointer; }
.csr-ma-preview img { width:100%; height:100%; object-fit:contain; display:block; }
.csr-ma-binding { display:flex; flex-direction:column; gap:3px; font-size:10px; color:#96a5bb; }
.csr-ma-binding textarea { width:100%; min-height:64px; box-sizing:border-box; resize:vertical; border:1px solid #3e4a5f; border-radius:6px; background:#151a21; color:#dce6f4; padding:6px; font-size:10px; }
.csr-ma-status { min-height:15px; color:#8f9eb3; font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.csr-ma-status.error { color:#ff8f8f; }
.csr-ma-status.warn { color:#e6c36c; }
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

function readState(node) {
  const parsed = parseJson(node._csrAssetStateWidget?.value, {});
  const state = {};
  for (const [key] of ASSET_SLOTS) {
    const entry = parsed?.[key];
    state[key] = {
      file: typeof entry === "string" ? entry : String(entry?.file || ""),
      kind: key.startsWith("character_") && String(entry?.kind || "").toLowerCase() === "object" ? "object" : key.startsWith("character_") ? "person" : "",
    };
  }
  return state;
}

function maxUploadedCharacter(node) {
  let highest = 0;
  for (let index = 1; index <= MAX_CHARACTERS; index += 1) {
    if (node._csrAssetState[`character_${index}`]?.file) highest = index;
  }
  return highest;
}

function measuredContentHeight(root) {
  if (!root) return 0;
  const style = getComputedStyle(root);
  const paddingBottom = Number.parseFloat(style.paddingBottom) || 0;
  let bottom = 0;
  for (const child of root.children) {
    if (child.hidden || child.offsetHeight <= 0) continue;
    bottom = Math.max(bottom, child.offsetTop + child.offsetHeight);
  }
  return Math.ceil(bottom + paddingBottom);
}

function scheduleSlotLayout(node) {
  if (node._csrLayoutRaf) cancelAnimationFrame(node._csrLayoutRaf);
  node._csrLayoutRaf = requestAnimationFrame(() => {
    node._csrLayoutRaf = 0;
    updateSlotLayout(node);
  });
}

function settleSlotLayout(node) {
  for (const delay of [0, 80, 250, 600]) {
    setTimeout(() => {
      if (node._csrRoot) updateSlotLayout(node);
    }, delay);
  }
}

function updateSlotLayout(node) {
  const visible = node._visibleCharacters || DEFAULT_VISIBLE_CHARACTERS;
  for (let index = 1; index <= MAX_CHARACTERS; index += 1) {
    const refs = node._assetRefs[`character_${index}`];
    if (refs) refs.card.hidden = index > visible;
  }
  if (node._slotCount) node._slotCount.textContent = `替换物 ${visible}/${MAX_CHARACTERS}`;
  if (node._slotMinus) node._slotMinus.disabled = visible <= MIN_CHARACTERS || Boolean(node._csrAssetState[`character_${visible}`]?.file);
  if (node._slotPlus) node._slotPlus.disabled = visible >= MAX_CHARACTERS;
  const panel = node._csrPanelWidget;
  if (!panel) {
    node.setSize?.([Math.max(540, node.size?.[0] || 540), measuredContentHeight(node._csrRoot) + 64]);
  } else {
    const panelHeight = Math.max(280, measuredContentHeight(node._csrRoot));
    const heightGetter = () => panelHeight;
    panel.getMinHeight = heightGetter;
    panel.getMaxHeight = heightGetter;
    if (panel.options) {
      panel.options.getMinHeight = heightGetter;
      panel.options.getMaxHeight = heightGetter;
    }
    panel.computedHeight = panelHeight;
    const computed = node.computeSize?.() || [540, panelHeight + 64];
    const nodeWidth = Math.max(540, Number(node.size?.[0] || computed[0] || 0));
    node.setSize?.([nodeWidth, panelHeight + 64]);
  }
  node.setDirtyCanvas?.(true, true);
}

function setWidget(node, widgetNode, value) {
  if (!widgetNode) return;
  widgetNode.value = value;
  widgetNode.callback?.(value);
  node.setDirtyCanvas?.(true, true);
  node.graph?.setDirtyCanvas?.(true, true);
}

function commitState(node) {
  setWidget(node, node._csrAssetStateWidget, JSON.stringify(node._csrAssetState));
}

function inputUrl(file) {
  const clean = String(file || "").replace(/\\/g, "/");
  const slash = clean.lastIndexOf("/");
  return `/view?filename=${encodeURIComponent(slash >= 0 ? clean.slice(slash + 1) : clean)}&type=input&subfolder=${encodeURIComponent(slash >= 0 ? clean.slice(0, slash) : "")}`;
}

async function uploadAsset(node, file, key) {
  if (!file) return;
  const form = new FormData();
  form.append("image", file);
  form.append("type", "input");
  form.append("subfolder", "AICG3D-CSR/Media");
  try {
    const response = await api.fetchApi("/upload/image", { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `上传失败 (${response.status})`);
    node._csrAssetState[key] = {
      ...node._csrAssetState[key],
      file: [payload.subfolder, payload.name].filter(Boolean).join("/"),
    };
    commitState(node);
    renderAssets(node);
  } catch (error) {
    node._csrStatus.textContent = String(error?.message || error);
    node._csrStatus.classList.add("error");
  }
}

function renderAssets(node) {
  for (const [key, label] of ASSET_SLOTS) {
    const refs = node._assetRefs[key];
    const file = node._csrAssetState[key]?.file || "";
    refs.preview.replaceChildren(refs.input);
    if (file) {
      const image = el("img");
      image.src = inputUrl(file);
      image.alt = label;
      refs.preview.append(image);
      refs.remove.hidden = false;
    } else {
      refs.preview.append(el("span", "", "点击上传"));
      refs.remove.hidden = true;
    }
  }
  const count = ASSET_SLOTS.filter(([key]) => node._csrAssetState[key]?.file).length;
  node._assetCount.textContent = `素材资源 ${count}/${ASSET_SLOTS.length}`;
  const characterCount = CHARACTER_KEYS.filter((key) => node._csrAssetState[key]?.file && node._csrAssetState[key]?.kind !== "object").length;
  const objectCount = CHARACTER_KEYS.filter((key) => node._csrAssetState[key]?.file && node._csrAssetState[key]?.kind === "object").length;
  const notices = [];
  if (characterCount >= 5) notices.push(`${characterCount} 个人物已启用：建议检查一致性或拆分顺序替换`);
  if (objectCount > 0) notices.push(`${objectCount} 个物品/产品参考已启用`);
  if (count > 9) notices.push(`当前 ${count} 张图片参考，超过 H3 单次 9 张上限`);
  node._csrStatus.textContent = notices.join("；");
  node._csrStatus.classList.toggle("warn", notices.length > 0);
  node._csrStatus.classList.remove("error");
  if (node._slotCount) updateSlotLayout(node);
}

function createPanel(node) {
  ensureStyle();
  const root = el("div", "csr-ma");
  const head = el("div", "csr-ma-head");
  head.append(el("span", "csr-ma-title", "MiniMax H3 Aicg资源库"), el("span", "csr-ma-tag", "人物 / 物品 / 产品"));
  root.append(head);

  const slotbar = el("div", "csr-ma-slotbar");
  const slotCount = el("span", "", "替换物 2/7");
  slotbar.append(slotCount, el("span", "spacer", ""));
  const slotMinus = el("button", "", "−");
  const slotPlus = el("button", "", "+");
  slotMinus.type = slotPlus.type = "button";
  slotbar.append(slotMinus, slotPlus);
  root.append(slotbar);

  const assetCount = el("div", "csr-ma-title", `素材资源 0/${ASSET_SLOTS.length}`);
  root.append(assetCount);
  const assets = el("div", "csr-ma-assets");
  root.append(assets);

  const bindingBox = el("label", "csr-ma-binding");
  bindingBox.append(el("span", "", "主体绑定（人物 / 物品）"));
  const bindingInput = el("textarea");
  bindingInput.value = String(widget(node, "character_bindings")?.value || "");
  bindingInput.onchange = () => setWidget(node, widget(node, "character_bindings"), bindingInput.value);
  bindingBox.append(bindingInput);
  root.append(bindingBox);

  const status = el("div", "csr-ma-status", "");
  root.append(status);

  Object.assign(node, {
    _csrRoot: root,
    _assetCount: assetCount,
    _slotCount: slotCount,
    _slotMinus: slotMinus,
    _slotPlus: slotPlus,
    _assetRefs: {},
    _csrStatus: status,
    _csrAssetStateWidget: widget(node, "asset_state"),
  });
  node._csrBindingObserver = new ResizeObserver(() => scheduleSlotLayout(node));
  node._csrBindingObserver.observe(bindingInput);
  node._csrBindingObserver.observe(assets);
  node._csrAssetState = readState(node);
  node._visibleCharacters = Math.min(MAX_CHARACTERS, Math.max(DEFAULT_VISIBLE_CHARACTERS, maxUploadedCharacter(node)));
  hideWidget(node._csrAssetStateWidget);
  const bindings = widget(node, "character_bindings");
  hideWidget(bindings);

  for (const [key, label] of ASSET_SLOTS) {
    const card = el("div", "csr-ma-card");
    if (key === "reference") {
      card.title = "背景替换时，此首帧不会作为最终环境锚点，避免旧背景覆盖新场景。";
    }
    const top = el("div", "csr-ma-top");
    const remove = el("button", "x", "×");
    remove.title = `清除${label}`;
    const kindSelect = key.startsWith("character_") ? el("select") : null;
    if (kindSelect) {
      kindSelect.append(new Option("人物", "person"), new Option("物品/产品", "object"));
      kindSelect.value = node._csrAssetState[key]?.kind || "person";
      kindSelect.title = "选择这个参考图用于替换人物，还是替换物品/产品/背包/道具";
      kindSelect.onchange = () => {
        node._csrAssetState[key].kind = kindSelect.value;
        commitState(node);
        renderAssets(node);
      };
      top.append(el("span", "", label), kindSelect, remove);
    } else {
      top.append(el("span", "", label), remove);
    }
    const preview = el("div", "csr-ma-preview");
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.hidden = true;
    preview.onclick = () => input.click();
    input.onchange = () => uploadAsset(node, input.files?.[0], key);
    remove.onclick = (event) => {
      event.stopPropagation();
      node._csrAssetState[key] = { ...node._csrAssetState[key], file: "" };
      commitState(node);
      renderAssets(node);
    };
    preview.append(input);
    card.append(top, preview);
    assets.append(card);
    node._assetRefs[key] = { card, preview, remove, label, input, kindSelect };
  }

  root.onpointerdown = root.onmousedown = root.ontouchstart = (event) => event.stopPropagation();
  slotMinus.onclick = (event) => {
    event.stopPropagation();
    if (node._visibleCharacters <= MIN_CHARACTERS) return;
    if (node._csrAssetState[`character_${node._visibleCharacters}`]?.file) return;
    node._visibleCharacters -= 1;
    updateSlotLayout(node);
  };
  slotPlus.onclick = (event) => {
    event.stopPropagation();
    node._visibleCharacters = Math.min(MAX_CHARACTERS, node._visibleCharacters + 1);
    updateSlotLayout(node);
  };
  node._csrPanelWidget = node.addDOMWidget("csr_media_assets_panel", "AICG3D_CSR_MEDIA_ASSETS", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 430,
    getMaxHeight: () => 4096,
  });
  renderAssets(node);
  settleSlotLayout(node);
}

app.registerExtension({
  name: "AICG3D.CSR.MediaAssets",
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
        if (!this._csrAssetStateWidget) return;
        this._csrAssetState = readState(this);
        this._visibleCharacters = Math.min(MAX_CHARACTERS, Math.max(DEFAULT_VISIBLE_CHARACTERS, maxUploadedCharacter(this)));
        renderAssets(this);
        settleSlotLayout(this);
      }, 0);
      return result;
    };
  },
});
