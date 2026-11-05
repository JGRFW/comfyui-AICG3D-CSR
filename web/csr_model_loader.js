import { app } from "../../scripts/app.js";

const NODE_NAME = "CSRModelLoader";
const STYLE_ID = "aicg3d-csr-model-loader-style";
const MODEL_NAMES = ["fl2va_model", "ref2va_model", "task_mode", "text_encoder", "video_vae", "audio_vae", "attention_mode"];
const LORA_SLOTS = 8;

const CSS = `
.csr-loader { display:flex; flex-direction:column; gap:8px; width:100%; padding:8px 2px; color:var(--fg-color,#ddd); }
.csr-loader-head { display:flex; align-items:center; gap:8px; }
.csr-loader-logo { width:25px; height:25px; border-radius:6px; display:grid; place-items:center; background:#e9edf8; color:#2c4f93; font-size:11px; font-weight:700; }
.csr-loader-title { font-size:13px; font-weight:650; color:#eef3fb; }
.csr-loader-tag { margin-left:auto; border:1px solid #40516c; border-radius:999px; padding:2px 7px; color:#9fb4d6; font-size:10px; }
.csr-loader-sec { display:flex; flex-direction:column; gap:6px; padding-top:6px; border-top:1px solid #303947; }
.csr-loader-row { display:grid; grid-template-columns:92px minmax(0,1fr); gap:8px; align-items:center; font-size:11px; }
.csr-loader-row > span { color:#9eabc0; }
.csr-loader select, .csr-loader input[type=text] { width:100%; min-width:0; height:27px; border:1px solid #3e4a5f; border-radius:5px; background:#171c24; color:#e5edf8; padding:0 7px; font-size:11px; }
.csr-loader select:focus, .csr-loader input:focus { outline:none; border-color:#628dd0; }
.csr-lora-head { display:flex; align-items:center; gap:7px; color:#b9c7dc; font-size:11px; }
.csr-lora-head strong { color:#edf3fc; font-weight:600; }
.csr-lora-head .spacer { flex:1; }
.csr-lora-btn { height:24px; min-width:25px; border:1px solid #435066; border-radius:5px; background:#242b36; color:#d8e2f0; cursor:pointer; }
.csr-lora-btn:hover { border-color:#6d92c8; }
.csr-lora-rows { display:flex; flex-direction:column; gap:6px; }
.csr-lora-row { display:grid; grid-template-columns:24px minmax(0,1fr) 62px 22px; gap:6px; align-items:center; }
.csr-lora-num { color:#8ea3c2; font-size:10px; }
.csr-lora-strength { width:62px; height:27px; border:1px solid #3e4a5f; border-radius:5px; background:#151a21; color:#e2ebf7; text-align:right; padding:0 5px; }
.csr-lora-select { width:100%; min-width:0; height:27px; border:1px solid #3e4a5f; border-radius:5px; background:#171c24; color:#e5edf8; padding:0 7px; font-size:11px; }
.csr-lora-select:focus { outline:none; border-color:#628dd0; }
.csr-lora-toggle { width:22px; height:22px; border-radius:50%; border:1px solid #435066; background:#242b36; cursor:pointer; }
.csr-lora-toggle.on { border-color:#4e8c6f; background:#2e5745; }
.csr-loader-note { color:#8393ab; font-size:10px; min-height:14px; }
`;

function style() {
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

function valuesOf(w) {
  const values = w?.options?.values;
  if (Array.isArray(values)) return values;
  if (typeof values === "function") {
    try { return values(); } catch { return []; }
  }
  return [];
}

function isNone(value) {
  return !value || ["none", "无", "None"].includes(String(value));
}

function setValue(node, name, value) {
  const w = widget(node, name);
  if (!w) return;
  w.value = value;
  w.callback?.(value);
  node.setDirtyCanvas?.(true, true);
  node.graph?.setDirtyCanvas?.(true, true);
}

function hideWidget(w) {
  if (!w) return;
  w.computeSize = () => [0, -4];
  w.type = "hidden";
}

function filteredModelOptions(w, kind) {
  const options = valuesOf(w).filter(Boolean);
  const selected = String(w?.value || "");
  const keep = new Set();
  for (const item of options) {
    const low = String(item).toLowerCase();
    if (kind === "model" && /(minimax|h3|dasiwa|fasth3)/.test(low)) keep.add(item);
    if (kind === "clip" && /(qwen3vl.*minimax|minimax.*qwen)/.test(low)) keep.add(item);
    if (kind === "video_vae" && /minimax_h3/.test(low) && !/audio_vae/.test(low)) keep.add(item);
    if (kind === "audio_vae" && /audio_vae/.test(low)) keep.add(item);
  }
  if (selected) keep.add(selected);
  return [...keep];
}

function selectRow(label, options, value, onChange, placeholder) {
  const row = el("label", "csr-loader-row");
  row.append(el("span", "", label));
  const select = el("select");
  if (!options.includes(value) && value) options = [value, ...options];
  if (!options.length) options = [value || "none"];
  for (const option of options) {
    const node = el("option", "", option);
    node.value = option;
    select.append(node);
  }
  if (placeholder) select.title = placeholder;
  select.value = value;
  select.onchange = () => onChange(select.value);
  row.append(select);
  return { row, select };
}

function loraRow(node, index, options) {
  const row = el("div", "csr-lora-row");
  row.append(el("span", "csr-lora-num", String(index)));
  const select = el("select", "csr-lora-select");
  const placeholder = el("option", "", "选择 LoRA");
  placeholder.value = "none";
  select.append(placeholder);
  for (const item of options) {
    select.append(new Option(item, item));
  }
  const strength = el("input", "csr-lora-strength");
  strength.type = "number";
  strength.min = "-30";
  strength.max = "30";
  strength.step = "0.05";
  const toggle = el("button", "csr-lora-toggle", "");
  toggle.type = "button";
  toggle.title = "启用或停用这个 LoRA";

  const nameWidget = widget(node, `lora_${index}`);
  const strengthWidget = widget(node, `lora_${index}_strength`);
  const enabledWidget = widget(node, `lora_${index}_enabled`);
  const selectedName = isNone(nameWidget?.value) ? "none" : String(nameWidget.value);
  if (![...select.options].some((item) => item.value === selectedName)) select.append(new Option(selectedName, selectedName));
  select.value = selectedName;
  strength.value = Number(strengthWidget?.value ?? 1).toFixed(2);
  const isEnabled = () => !isNone(nameWidget?.value) && Boolean(enabledWidget?.value ?? true);
  const sync = () => {
    const currentName = isNone(nameWidget?.value) ? "none" : String(nameWidget.value);
    if (![...select.options].some((item) => item.value === currentName)) select.append(new Option(currentName, currentName));
    select.value = currentName;
    strength.value = Number(strengthWidget?.value ?? 1).toFixed(2);
    const enabled = isEnabled();
    toggle.classList.toggle("on", enabled);
    toggle.title = enabled ? "已启用，点击停用" : "已停用，点击启用";
    strength.disabled = !enabled;
    select.disabled = false;
  };
  select.onchange = () => {
    const value = select.value || "none";
    setValue(node, `lora_${index}`, value);
    setValue(node, `lora_${index}_enabled`, !isNone(value));
    sync();
  };
  strength.onchange = () => setValue(node, `lora_${index}_strength`, Number(strength.value));
  toggle.onclick = () => {
    if (isNone(nameWidget?.value)) {
      select.focus();
      return;
    }
    setValue(node, `lora_${index}_enabled`, !isEnabled());
    sync();
  };
  sync();
  row.append(select, strength, toggle);
  return { row, select, strength, sync };
}

function createPanel(node) {
  style();
  const root = el("div", "csr-loader");
  const head = el("div", "csr-loader-head");
  head.append(el("span", "csr-loader-logo", "AI"), el("span", "csr-loader-title", "MiniMax H3 Aicg 加载器"), el("span", "csr-loader-tag", "CSR 独立版"));
  root.append(head);

  const modelSec = el("div", "csr-loader-sec");
  const taskWidget = widget(node, "task_mode");
  const taskRow = selectRow("任务模式", valuesOf(taskWidget), String(taskWidget?.value || "Ref2VA（推荐）"), (value) => setValue(node, "task_mode", value));
  const namedSelects = { task_mode: taskRow.select };
  modelSec.append(taskRow.row);
  for (const [name, label, kind] of [
    ["fl2va_model", "FL2VA 模型", "model"],
    ["ref2va_model", "REF2VA 模型", "model"],
    ["text_encoder", "文本编码器", "clip"],
    ["video_vae", "视频 VAE", "video_vae"],
    ["audio_vae", "音频 VAE（预留）", "audio_vae"],
  ]) {
    const w = widget(node, name);
    const row = selectRow(label, filteredModelOptions(w, kind), String(w?.value || ""), (value) => setValue(node, name, value));
    namedSelects[name] = row.select;
    modelSec.append(row.row);
  }
  root.append(modelSec);

  const loraSec = el("div", "csr-loader-sec");
  const loraHead = el("div", "csr-lora-head");
  loraHead.append(el("strong", "", "LoRA"), el("span", "spacer", ""));
  const minus = el("button", "csr-lora-btn", "−");
  const plus = el("button", "csr-lora-btn", "+");
  const count = el("span", "", "3 / 8");
  minus.type = plus.type = "button";
  loraHead.append(minus, count, plus);
  loraSec.append(loraHead);

  const loraOptions = [...new Set(valuesOf(widget(node, "lora_1")).filter((item) => !isNone(item)))]
    .map(String)
    .sort((left, right) => left.localeCompare(right, undefined, { sensitivity: "base" }));

  const rowsBox = el("div", "csr-lora-rows");
  loraSec.append(rowsBox);
  const rows = [];
  const activeIndexes = [];
  for (let index = 1; index <= LORA_SLOTS; index += 1) {
    const enabled = widget(node, `lora_${index}_enabled`)?.value ?? true;
    if (enabled && !isNone(widget(node, `lora_${index}`)?.value)) activeIndexes.push(index);
  }
  let visible = Math.max(3, activeIndexes.length ? activeIndexes.at(-1) : 3);

  const rebuild = () => {
    while (rows.length < visible) {
      const entry = loraRow(node, rows.length + 1, loraOptions);
      rows.push(entry);
      rowsBox.append(entry.row);
    }
    while (rows.length > visible) rows.pop().row.remove();
    for (const entry of rows) entry.sync();
    count.textContent = `${visible} / ${LORA_SLOTS}`;
    minus.disabled = visible <= 1;
    plus.disabled = visible >= LORA_SLOTS;
  };
  minus.onclick = () => {
    if (visible <= 1) return;
    for (let index = visible; index > visible - 1; index -= 1) {
      setValue(node, `lora_${index}_enabled`, false);
    }
    visible -= 1;
    rebuild();
  };
  plus.onclick = () => {
    visible = Math.min(LORA_SLOTS, visible + 1);
    rebuild();
  };
  root.append(loraSec);
  const note = el("div", "csr-loader-note", "下拉列表可滚动选择；圆形开关只停用 LoRA，不会清除选择或强度");
  root.append(note);

  Object.assign(node, { _csrNamedSelects: namedSelects, _csrLoraRows: rows, _csrLoraRebuild: rebuild });

  for (const name of MODEL_NAMES) hideWidget(widget(node, name));
  for (let index = 1; index <= LORA_SLOTS; index += 1) {
    hideWidget(widget(node, `lora_${index}`));
    hideWidget(widget(node, `lora_${index}_strength`));
    hideWidget(widget(node, `lora_${index}_enabled`));
  }

  root.onpointerdown = root.onmousedown = root.ontouchstart = (event) => event.stopPropagation();
  node.addDOMWidget("csr_model_loader_panel", "AICG3D_CSR_MODEL_LOADER", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 470,
    getMaxHeight: () => 760,
  });
  rebuild();
  setTimeout(() => node.setSize?.([Math.max(480, node.size?.[0] || 480), Math.max(700, node.size?.[1] || 700)]), 0);
}

app.registerExtension({
  name: "AICG3D.CSR.ModelLoader",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;
    style();
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
        for (const [name, select] of Object.entries(this._csrNamedSelects || {})) {
          const value = String(widget(this, name)?.value || "");
          if (value && ![...select.options].some((item) => item.value === value)) select.append(new Option(value, value));
          if (value) select.value = value;
        }
        this._csrLoraRebuild?.();
      }, 0);
      return result;
    };
  },
});
