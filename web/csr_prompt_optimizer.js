import { api } from "../../scripts/api.js";

const STYLE_ID = "aicg3d-csr-prompt-optimizer-style";
const CONFIG_URL = "/aicg3d_csr/prompt_optimizer/config";
const MODELS_URL = "/aicg3d_csr/prompt_optimizer/models";
const OPTIMIZE_URL = "/aicg3d_csr/prompt_optimizer/optimize";
const DEFAULT_SCHEMES = {
  auto: "跟随替换标签",
  background_replace: "背景彻底替换",
  scene_rebuild: "场景结构重建",
  person_replace: "人物身份替换",
  object_replace: "物品/产品替换",
  person_scene: "人物 + 场景",
  person_object: "人物 + 物品",
  composite: "综合替换",
  background_repair: "修复：背景没有被替换",
  foreground_preserve: "修复：前景人物被误改",
};
const CSS = `
.csr-opt-overlay { position:fixed; inset:0; z-index:10020; display:flex; align-items:center; justify-content:center; padding:18px; background:rgba(4,7,12,.72); }
.csr-opt-dialog { width:min(820px,calc(100vw - 36px)); max-height:min(880px,calc(100vh - 36px)); overflow:auto; border:1px solid #43536c; border-radius:8px; background:#151b24; color:#e5edf8; box-shadow:0 24px 80px rgba(0,0,0,.55); }
.csr-opt-head { display:flex; align-items:center; gap:8px; padding:12px 14px; border-bottom:1px solid #303b4c; }
.csr-opt-title { font-size:14px; font-weight:650; color:#f1f6fd; }
.csr-opt-close { margin-left:auto; width:28px; height:26px; border:1px solid #46546a; border-radius:5px; background:#202834; color:#dfe8f5; cursor:pointer; }
.csr-opt-body { display:flex; flex-direction:column; gap:10px; padding:12px 14px; }
.csr-opt-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }
.csr-opt-field { display:flex; flex-direction:column; gap:4px; min-width:0; color:#9eabc0; font-size:10px; }
.csr-opt-field.wide { grid-column:1/-1; }
.csr-opt-field input, .csr-opt-field select, .csr-opt-field textarea { width:100%; min-width:0; border:1px solid #43536a; border-radius:5px; background:#0f151d; color:#edf4ff; padding:0 7px; font-size:11px; box-sizing:border-box; }
.csr-opt-field input, .csr-opt-field select { height:29px; }
.csr-opt-field textarea { min-height:112px; resize:vertical; padding:7px; line-height:1.45; }
.csr-opt-field textarea.csr-opt-output { min-height:180px; }
.csr-opt-inline { display:flex; gap:6px; }
.csr-opt-inline input, .csr-opt-inline select { flex:1; }
.csr-opt-vision { display:flex; align-items:flex-start; gap:8px; padding:8px; border:1px solid #354253; border-radius:6px; background:#1b222c; color:#b8c7da; font-size:10px; line-height:1.4; }
.csr-opt-vision input { width:15px; height:15px; margin:1px 0 0; flex:0 0 auto; accent-color:#5d8fd8; }
.csr-opt-vision strong { display:block; color:#e8f0fb; font-size:11px; font-weight:600; }
.csr-opt-vision-note { color:#8fa1b9; }
.csr-opt-vision-details { border-top:1px solid #303b4c; margin-top:4px; padding-top:8px; }
.csr-opt-action { height:29px; border:1px solid #455268; border-radius:5px; background:#232c38; color:#dbe6f5; padding:0 10px; cursor:pointer; white-space:nowrap; }
.csr-opt-action.primary { border-color:#4b79b5; background:#23446c; color:#f0f7ff; }
.csr-opt-action:disabled { opacity:.45; cursor:default; }
.csr-opt-actions { display:flex; align-items:center; gap:7px; flex-wrap:wrap; }
.csr-opt-status { min-height:16px; color:#96a5b9; font-size:10px; white-space:pre-wrap; }
.csr-opt-status.error { color:#ff9f9f; }
.csr-opt-status.ok { color:#94d5ad; }
.csr-opt-hidden { display:none !important; }
@media (max-width:680px) { .csr-opt-grid { grid-template-columns:1fr; } .csr-opt-field.wide { grid-column:auto; } }
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

function setWidgetValue(node, name, value) {
  const target = widget(node, name);
  if (!target) return;
  target.value = value;
  target.callback?.(value);
  node.setDirtyCanvas?.(true, true);
  node.graph?.setDirtyCanvas?.(true, true);
}

function parseJson(value, fallback) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function graphNodes(graph) {
  return graph?._nodes || graph?.nodes || [];
}

function graphLink(graph, id) {
  const links = graph?.links;
  if (!links || id == null) return null;
  if (typeof links.get === "function") return links.get(id) || links.get(String(id)) || null;
  return links[id] || null;
}

function originNode(graph, input) {
  if (!input) return null;
  const link = input.link && typeof input.link === "object" ? input.link : graphLink(graph, input.link);
  const originId = Array.isArray(link)
    ? link[1]
    : link?.origin_id ?? link?.originId ?? link?.origin?.id;
  if (originId == null) return null;
  return graph?.getNodeById?.(originId) || graphNodes(graph).find((item) => String(item?.id) === String(originId)) || null;
}

function upstreamNodes(node) {
  const result = [];
  const seen = new Set([node]);
  const queue = [];
  const graph = node?.graph;
  for (const input of node?.inputs || []) {
    const origin = originNode(graph, input);
    if (origin) queue.push(origin);
  }
  while (queue.length) {
    const current = queue.shift();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    result.push(current);
    for (const input of current.inputs || []) {
      const origin = originNode(current.graph || graph, input);
      if (origin && !seen.has(origin)) queue.push(origin);
    }
  }
  return result;
}

function visualMediaContext(node) {
  const ancestors = upstreamNodes(node);
  const crop = ancestors.find((item) => item?.type === "CSRVideoCrop");
  const assets = ancestors.find((item) => item?.type === "CSRMediaAssets");
  const videoState = parseJson(widget(crop, "video_state")?.value, {});
  const videoEntry = videoState?.video;
  const video = typeof videoEntry === "string" ? videoEntry : String(videoEntry?.file || "");
  const rows = parseJson(widget(crop, "segment_ranges")?.value, []);
  const first = Array.isArray(rows) ? rows[0] : null;
  const start = Number(Array.isArray(first) ? first[0] : first?.start);
  const end = Number(Array.isArray(first) ? first[1] : first?.end);
  const assetState = parseJson(widget(assets, "asset_state")?.value, {});
  const images = [];
  for (const [key, raw] of Object.entries(assetState || {})) {
    const entry = typeof raw === "string" ? { file: raw } : (raw || {});
    const file = String(entry.file || "");
    if (!file) continue;
    let kind = "reference";
    let label = "参考素材";
    if (key === "background") {
      kind = "background";
      label = "背景/场景参考";
    } else if (key === "reference") {
      label = "参考 / 首帧";
    } else if (key.startsWith("character_")) {
      const index = key.slice("character_".length);
      kind = String(entry.kind || "person").toLowerCase() === "object" ? "object" : "person";
      label = kind === "object" ? `替换物 ${index}` : `人物参考 ${index}`;
    }
    images.push({ file, kind, label });
  }
  return {
    video,
    video_start: Number.isFinite(start) ? start : 0,
    video_end: Number.isFinite(end) ? end : 1,
    video_duration: Number(crop?._csrInfo?.duration || 0),
    images,
  };
}

function field(label, control, wide = false) {
  const box = el("label", `csr-opt-field${wide ? " wide" : ""}`);
  box.append(el("span", "", label), control);
  return box;
}

export function createPromptOptimizer(node, tagSelect) {
  ensureStyle();
  const button = el("button", "csr-opt-open", "提示词优化");
  let ui = null;
  let controller = null;

  const close = () => {
    controller?.abort();
    controller = null;
    ui?.overlay.remove();
    ui = null;
  };

  const status = (text, kind = "") => {
    if (!ui) return;
    ui.status.textContent = text;
    ui.status.className = `csr-opt-status${kind ? ` ${kind}` : ""}`;
  };

  const busy = (value) => {
    if (!ui) return;
    ui.optimize.disabled = value;
    ui.save.disabled = value;
    ui.refresh.disabled = value;
    ui.optimize.textContent = value ? "优化中..." : "优化提示词";
    ui.cancel.classList.toggle("csr-opt-hidden", !value);
  };

  const modeChanged = () => {
    if (!ui) return;
    const local = ui.mode.value === "local";
    ui.apiGroup.classList.toggle("csr-opt-hidden", local);
    ui.localGroup.classList.toggle("csr-opt-hidden", !local);
    ui.apiVisionField.classList.toggle("csr-opt-hidden", local);
    ui.localVisionField.classList.toggle("csr-opt-hidden", !local);
    ui.keyHint.textContent = local ? "" : (ui.keyHint.dataset.saved === "true" ? "已保存密钥；留空继续使用" : "");
    visionChanged();
  };

  const visionChanged = () => {
    if (!ui) return;
    const enabled = Boolean(ui.visionEnabled.checked);
    ui.visionDetails.classList.toggle("csr-opt-hidden", !enabled);
    const selected = ui.mode.value === "local" ? Boolean(ui.localMmproj.value) : Boolean(ui.visionModel.value.trim());
    ui.visionNote.textContent = enabled
      ? (selected
        ? "已选择视觉模型：会读取目标段首/中/尾帧及少量参考图。"
        : "请选择对应的视觉模型；未选择时仍只发送文字。")
      : "默认关闭：不读取视频或图片，只发送文字描述。";
  };

  const apiModels = (items) => {
    if (!ui) return;
    ui.modelList.replaceChildren();
    for (const item of items || []) {
      const name = String(item || "").trim();
      if (name) ui.modelList.append(new Option(name, name));
    }
  };

  const localModels = (items, selected = "") => {
    if (!ui) return;
    ui.localModel.replaceChildren();
    const models = (items || []).filter((item) => item && typeof item === "object");
    if (!models.length) {
      ui.localModel.append(new Option("未找到 GGUF 模型", ""));
    } else {
      for (const item of models) {
        ui.localModel.append(new Option(`${item.name} · ${(Number(item.size) / 1024 ** 3).toFixed(2)} GB`, item.path));
      }
    }
    if (selected && ![...ui.localModel.options].some((item) => item.value === selected)) {
      ui.localModel.append(new Option(selected, selected));
    }
    if (selected) ui.localModel.value = selected;
  };

  const mmprojFiles = (items, selected = "") => {
    if (!ui) return;
    ui.localMmproj.replaceChildren(new Option("未选择视觉投影", ""));
    const files = (items || []).filter((item) => item && typeof item === "object");
    for (const item of files) {
      ui.localMmproj.append(new Option(`${item.name} · ${(Number(item.size) / 1024 ** 2).toFixed(0)} MB`, item.path));
    }
    const value = String(selected || "");
    if (value && ![...ui.localMmproj.options].some((item) => item.value === value)) {
      ui.localMmproj.append(new Option(value, value));
    }
    ui.localMmproj.value = value;
  };

  const fill = (config) => {
    if (!ui) return;
    const modes = config.modes || { api: "OpenAI 兼容 API", local: "本地 GGUF" };
    const schemes = config.schemes || DEFAULT_SCHEMES;
    const languages = config.languages || { English: "英文（H3 推荐）", "中文": "中文" };
    const strengths = config.strengths || { concise: "简洁", balanced: "标准", strong: "强化" };
    ui.mode.replaceChildren(...Object.entries(modes).map(([value, label]) => new Option(label, value)));
    ui.scheme.replaceChildren(...Object.entries(schemes).map(([value, label]) => new Option(label, value)));
    ui.language.replaceChildren(...Object.entries(languages).map(([value, label]) => new Option(label, value)));
    ui.strength.replaceChildren(...Object.entries(strengths).map(([value, label]) => new Option(label, value)));
    ui.mode.value = config.mode || "api";
    ui.apiBase.value = config.api_base || "http://127.0.0.1:11434/v1";
    ui.model.value = config.model || "qwen2.5:7b";
    ui.apiKey.value = "";
    ui.apiKey.placeholder = config.api_key_set ? "已保存，留空继续使用" : "本地 API 通常不需要";
    ui.keyHint.dataset.saved = config.api_key_set ? "true" : "false";
    ui.visionEnabled.checked = Boolean(config.vision_enabled);
    ui.visionModel.value = String(config.vision_model || "");
    ui.localContext.value = String(config.local_context || 8192);
    ui.localGpuLayers.value = String(config.local_gpu_layers ?? -1);
    ui.language.value = config.language || "English";
    ui.strength.value = config.strength || "balanced";
    ui.scheme.value = config.scheme || "auto";
    ui.temperature.value = String(config.temperature ?? 0.35);
    localModels(config.local_models || [], String(config.local_model || ""));
    mmprojFiles(config.mmproj_files || [], String(config.local_mmproj || ""));
    ui.llamaStatus.textContent = config.llama_cpp_available
      ? "llama.cpp 可用"
      : "GGUF 直载需安装 llama-cpp-python";
    visionChanged();
    modeChanged();
  };

  const collect = () => ({
    mode: ui.mode.value,
    api_base: ui.apiBase.value.trim(),
    api_key: ui.apiKey.value,
    model: ui.model.value.trim(),
    vision_enabled: Boolean(ui.visionEnabled.checked),
    vision_model: ui.visionModel.value.trim(),
    local_model: ui.localModel.value,
    local_mmproj: ui.localMmproj.value,
    local_context: Number(ui.localContext.value) || 8192,
    local_gpu_layers: Number(ui.localGpuLayers.value) || 0,
    language: ui.language.value,
    strength: ui.strength.value,
    scheme: ui.scheme.value,
    temperature: Number(ui.temperature.value) || 0.35,
  });

  const save = async (silent = false) => {
    const response = await api.fetchApi(CONFIG_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `保存失败 (${response.status})`);
    fill(data);
    if (!silent) status("设置已保存", "ok");
    return data;
  };

  const refresh = async () => {
    try {
      status("正在读取模型列表...");
      await save(true);
      const response = await api.fetchApi(MODELS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collect()),
      });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || `模型列表失败 (${response.status})`);
      if (ui.mode.value === "local") {
        localModels(data.models || [], ui.localModel.value);
      } else {
        apiModels(data.models || []);
      }
      if (ui.mode.value === "api" && !ui.model.value && data.models?.length) ui.model.value = String(data.models[0]);
      status(`已读取 ${data.models?.length || 0} 个模型`, "ok");
    } catch (error) {
      status(String(error?.message || error), "error");
    }
  };

  const build = () => {
    const overlay = el("div", "csr-opt-overlay");
    const dialog = el("div", "csr-opt-dialog");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    const head = el("div", "csr-opt-head");
    head.append(el("span", "csr-opt-title", "提示词优化"));
    const closeButton = el("button", "csr-opt-close", "×");
    closeButton.type = "button";
    closeButton.onclick = close;
    head.append(closeButton);

    const body = el("div", "csr-opt-body");
    const grid = el("div", "csr-opt-grid");
    const mode = el("select");
    const scheme = el("select");
    const apiBase = el("input");
    const apiKey = el("input");
    apiKey.type = "password";
    apiKey.autocomplete = "off";
    const model = el("input");
    model.setAttribute("list", "csr-opt-model-list");
    const modelList = el("datalist");
    modelList.id = "csr-opt-model-list";
    const visionEnabled = el("input");
    visionEnabled.type = "checkbox";
    const visionModel = el("input");
    visionModel.setAttribute("list", "csr-opt-model-list");
    visionModel.placeholder = "留空则使用上面的文本模型";
    const localMmproj = el("select");
    const localModel = el("select");
    const localContext = el("input");
    localContext.type = "number";
    localContext.min = "2048";
    localContext.max = "131072";
    localContext.step = "1024";
    const localGpuLayers = el("input");
    localGpuLayers.type = "number";
    localGpuLayers.min = "-1";
    localGpuLayers.max = "999";
    const language = el("select");
    const strength = el("select");
    const temperature = el("input");
    temperature.type = "number";
    temperature.min = "0";
    temperature.max = "1.5";
    temperature.step = "0.05";
    const source = el("textarea");
    source.value = String(widget(node, "description")?.value || "");
    const output = el("textarea", "csr-opt-output");
    output.readOnly = true;

    const apiGrid = el("div", "csr-opt-grid");
    const apiGroup = el("div", "csr-opt-field wide csr-opt-api-group");
    const keyHint = el("span", "csr-opt-status");
    apiGrid.append(field("API 地址", apiBase), field("API Key", apiKey), field("模型", model));
    apiGrid.append(modelList);
    apiGroup.append(apiGrid, keyHint);

    const apiVisionField = field("视觉模型（可选）", visionModel, true);
    const localVisionField = field("视觉投影 mmproj", localMmproj, true);
    const visionGrid = el("div", "csr-opt-grid");
    visionGrid.append(apiVisionField, localVisionField);
    const visionDetails = el("div", "csr-opt-vision-details wide csr-opt-hidden");
    visionDetails.append(visionGrid);

    const visionBox = el("label", "csr-opt-vision wide");
    const visionCopy = el("span");
    visionCopy.append(el("strong", "", "启用视觉分析（读取参考素材）"));
    const visionNote = el("span", "csr-opt-vision-note", "默认关闭：不读取视频或图片，只发送文字描述。");
    visionCopy.append(visionNote);
    visionBox.append(visionEnabled, visionCopy);

    const localGrid = el("div", "csr-opt-grid");
    localGrid.append(
      field("GGUF 模型", localModel, true),
      field("上下文", localContext),
      field("GPU 层数（-1 自动）", localGpuLayers),
    );
    const localGroup = el("div", "csr-opt-field wide csr-opt-local-group csr-opt-hidden");
    localGroup.append(localGrid);

    grid.append(
      field("运行方式", mode),
      field("提示词方案", scheme),
      field("输出语言", language),
      field("细节强度", strength),
      field("温度", temperature),
      field("当前描述", source, true),
      apiGroup,
      localGroup,
      visionBox,
      visionDetails,
      field("优化结果", output, true),
    );

    const actions = el("div", "csr-opt-actions");
    const refreshButton = el("button", "csr-opt-action", "刷新模型");
    const saveButton = el("button", "csr-opt-action", "保存设置");
    const optimize = el("button", "csr-opt-action primary", "优化提示词");
    const apply = el("button", "csr-opt-action", "应用到描述");
    const cancel = el("button", "csr-opt-action csr-opt-hidden", "取消");
    const llamaStatus = el("span", "csr-opt-status");
    for (const item of [refreshButton, saveButton, optimize, apply, cancel]) item.type = "button";
    actions.append(refreshButton, saveButton, optimize, apply, cancel, llamaStatus);
    const statusLine = el("div", "csr-opt-status");
    body.append(grid, actions, statusLine);
    dialog.append(head, body);
    overlay.append(dialog);

    ui = {
      overlay, mode, scheme, apiBase, apiKey, model, modelList, localModel,
      visionEnabled, visionModel, localMmproj, visionDetails, visionNote, apiVisionField, localVisionField,
      localContext, localGpuLayers, language, strength, temperature, source,
      output, apiGroup, localGroup, keyHint, refresh: refreshButton, save: saveButton,
      optimize, apply, cancel, status: statusLine, llamaStatus,
    };
    mode.onchange = modeChanged;
    visionEnabled.onchange = visionChanged;
    visionModel.oninput = visionChanged;
    localMmproj.onchange = visionChanged;
    refreshButton.onclick = refresh;
    saveButton.onclick = async () => {
      try {
        status("正在保存...");
        await save(false);
      } catch (error) {
        status(String(error?.message || error), "error");
      }
    };
    optimize.onclick = async () => {
      controller?.abort();
      controller = new AbortController();
      busy(true);
      const visionModelReady = ui.mode.value === "local" ? Boolean(ui.localMmproj.value) : Boolean(ui.visionModel.value.trim());
      const useVision = ui.visionEnabled.checked && visionModelReady;
      const media = useVision ? visualMediaContext(node) : null;
      const visualCount = Number(Boolean(media?.video)) + (media?.images?.length || 0);
      const statusKind = useVision && !visualCount ? "error" : "";
      status(
        ui.visionEnabled.checked
          ? (!visionModelReady ? "未选择视觉模型，本次按纯文本优化..." : (visualCount ? `正在读取 ${visualCount} 个上游素材并优化提示词...` : "未找到上游视觉素材，本次只发送文字描述..."))
          : "正在生成纯文字优化提示词...",
        statusKind,
      );
      try {
        await save(true);
        const response = await api.fetchApi(OPTIMIZE_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            request_id: globalThis.crypto?.randomUUID?.() || String(Date.now()),
            description: source.value,
            replacement_tag: tagSelect.value,
            scheme: scheme.value,
            config: collect(),
            ...(useVision && media ? { media } : {}),
          }),
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || `优化失败 (${response.status})`);
        output.value = String(data.prompt || "");
        if (!output.value) throw new Error("本地模型返回了空提示词。");
        status("优化完成，可先检查再应用。", "ok");
      } catch (error) {
        if (error?.name !== "AbortError") status(String(error?.message || error), "error");
      } finally {
        controller = null;
        busy(false);
      }
    };
    apply.onclick = () => {
      const value = output.value.trim();
      if (!value) {
        status("没有可应用的优化结果。", "error");
        return;
      }
      setWidgetValue(node, "description", value);
      source.value = value;
      status("已写入替换描述。", "ok");
    };
    cancel.onclick = () => controller?.abort();
    overlay.onclick = (event) => {
      if (event.target === overlay) close();
    };
    dialog.onpointerdown = dialog.onmousedown = dialog.ontouchstart = (event) => event.stopPropagation();
    return overlay;
  };

  button.onclick = async (event) => {
    event.stopPropagation();
    if (ui) {
      ui.source.focus();
      return;
    }
    document.body.append(build());
    modeChanged();
    visionChanged();
    try {
      status("正在读取优化器设置...");
      const response = await api.fetchApi(CONFIG_URL);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || `设置读取失败 (${response.status})`);
      fill(data);
      status("设置已加载", "ok");
    } catch (error) {
      status(String(error?.message || error), "error");
    }
  };
  return button;
}
