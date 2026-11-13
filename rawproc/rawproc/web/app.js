"use strict";

const $ = (id) => document.getElementById(id);
let currentSidecar = "";
let currentStage = "srgb";
let stageNames = {};

function qsExtra() {
  const p = new URLSearchParams();
  p.set("sidecar", currentSidecar);
  if ($("auto-wb").checked) {
    p.set("auto", "1");
  } else {
    p.set("wr", $("gain-r").value);
    p.set("wg", $("gain-g").value);
    p.set("wb", $("gain-b").value);
  }
  return p.toString();
}

function setStatus(text, isError) {
  const el = $("status");
  el.textContent = text;
  el.className = "status " + (isError ? "error" : "ok");
}

async function loadSamples() {
  const res = await fetch("/api/samples");
  const data = await res.json();
  if (!data.ok) {
    setStatus(data.error, true);
    return;
  }
  const sel = $("sample-select");
  sel.innerHTML = "";
  for (const s of data.samples) {
    const opt = document.createElement("option");
    opt.value = s.sidecar;
    opt.textContent = `${s.name} — ${s.width}×${s.height} ${s.cfa_layout}`;
    opt.dataset.meta = JSON.stringify(s);
    sel.appendChild(opt);
  }
  if (data.samples.length) {
    sel.selectedIndex = 0;
    showSampleMeta();
  }
}

function showSampleMeta() {
  const opt = $("sample-select").selectedOptions[0];
  if (!opt) return;
  const s = JSON.parse(opt.dataset.meta);
  currentSidecar = s.sidecar;
  $("sample-meta").innerHTML = `
    <dl>
      <dt>说明</dt><dd>${s.description || "（无）"}</dd>
      <dt>CFA 排列 / R 原点</dt><dd>${s.cfa_layout} / [${s.cfa_origin.join(", ")}]</dd>
      <dt>裁切原点 / 尺寸</dt><dd>[${s.crop_origin.join(", ")}] / [${s.crop_size.join(", ")}]</dd>
      <dt>旋转 (EXIF)</dt><dd>${s.orientation}</dd>
      <dt>黑电平 r/g1/g2/b</dt>
      <dd>${s.black_levels.r} / ${s.black_levels.g1} / ${s.black_levels.g2} / ${s.black_levels.b}</dd>
      <dt>白电平</dt><dd>${s.white_level}</dd>
    </dl>`;
}

async function develop() {
  if (!currentSidecar) {
    setStatus("请先选择样本", true);
    return;
  }
  setStatus("显影中…", false);
  try {
    const res = await fetch("/api/process?" + qsExtra());
    const data = await res.json();
    if (!data.ok) throw new Error(data.error);

    const wb = data.wb_gains;
    if ($("auto-wb").checked) {
      $("gain-r").value = wb.r.toFixed(4);
      $("gain-g").value = wb.g.toFixed(4);
      $("gain-b").value = wb.b.toFixed(4);
    }

    const bar = $("stage-buttons");
    bar.innerHTML = "";
    stageNames = {};
    for (const [key, label] of data.stages) {
      stageNames[key] = label;
      const btn = document.createElement("button");
      btn.textContent = label;
      btn.dataset.stage = key;
      btn.onclick = () => showStage(key);
      bar.appendChild(btn);
    }

    const tbody = $("stats-table").querySelector("tbody");
    tbody.innerHTML = "";
    for (const st of data.channel_stats) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${st.channel}</td><td>${st.count}</td>
        <td>${st.min}</td><td>${st.max}</td><td>${st.mean.toFixed(1)}</td>
        <td>${st.black}</td><td>${st.white}</td>`;
      tbody.appendChild(tr);
    }
    $("stats-table").querySelector("thead")?.remove();
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>通道</th><th>样本数</th><th>最小</th><th>最大</th><th>均值</th><th>黑电平</th><th>白电平</th></tr>";
    $("stats-table").prepend(thead);

    const warn = $("warnings");
    warn.innerHTML = "";
    if (data.warnings.length) {
      for (const w of data.warnings) {
        const div = document.createElement("div");
        div.className = "warning";
        div.textContent = "⚠ " + w;
        warn.appendChild(div);
      }
    }

    const dec = data.decoder;
    const wbText = dec.as_shot_wb
      ? dec.as_shot_wb.map((v) => v.toFixed(4)).join(", ")
      : "样本未声明（不默认 1,1,1）";
    $("decoder-info").innerHTML = `
      <dl>
        <dt>RAW 解码依赖</dt>
        <dd>${dec.name} ${dec.version}（基础显影走 v2 新路径）</dd>
        <dt>有效像素窗口（行,列 / 高,宽）</dt>
        <dd>[${dec.active_window_origin.join(", ")}] /
            [${dec.active_window_size.join(", ")}]</dd>
        <dt>机内白平衡系数 R,G,B</dt>
        <dd>${wbText}</dd>
        <dt>当前工作增益 R,G,B</dt>
        <dd>${wb.r.toFixed(4)}, ${wb.g.toFixed(4)}, ${wb.b.toFixed(4)}</dd>
      </dl>`;

    setStatus(`显影完成：${data.width}×${data.height}，` +
      `${data.warnings.length} 条提示。高位深数值见像素检视。`, false);
    showStage(currentStage);
  } catch (err) {
    setStatus("显影失败：" + err.message, true);
  }
}

function showStage(stage) {
  currentStage = stage;
  for (const btn of $("stage-buttons").querySelectorAll("button")) {
    btn.classList.toggle("active", btn.dataset.stage === stage);
  }
  $("stage-title").textContent = "结果区 — " + (stageNames[stage] || stage);
  $("stage-image").src = "/api/image?" + qsExtra() +
    "&stage=" + encodeURIComponent(stage) + "&t=" + Date.now();
}

async function inspectPixel(row, col) {
  const p = new URLSearchParams();
  p.set("sidecar", currentSidecar);
  p.set("r", row);
  p.set("c", col);
  if ($("auto-wb").checked) p.set("auto", "1");
  else {
    p.set("wr", $("gain-r").value);
    p.set("wg", $("gain-g").value);
    p.set("wb", $("gain-b").value);
  }
  const res = await fetch("/api/pixel?" + p.toString());
  const data = await res.json();
  if (!data.ok) {
    setStatus(data.error, true);
    return;
  }
  const x = data.pixel;
  const f = (v) => Number(v).toFixed(6);
  $("pixel-inspector").textContent =
`位置 (行=${x.row}, 列=${x.col})
CFA 通道        : ${x.cfa_channel} (索引 ${x.cfa_index})
原始 uint16     : ${x.raw_uint16}
归一化马赛克值  : ${f(x.normalized_mosaic)}
过黑标记        : ${x.under_black}
饱和标记        : ${x.saturated}
线性去马赛克 RGB: ${x.linear_demosaic_rgb.map(f).join(", ")}
线性白平衡 RGB  : ${x.linear_wb_rgb.map(f).join(", ")}
16 位编码 RGB   : ${x.linear16_rgb.join(", ")}  (0..65535，真实运算后取整)
sRGB 8 位预览   : ${x.srgb8_rgb.join(", ")}  (仅预览，独立曲线)`;
}

async function saveResults() {
  if (!currentSidecar) {
    setStatus("请先选择并显影样本", true);
    return;
  }
  const stem = $("sample-select").selectedOptions[0]
    .textContent.split(" ")[0].replace(/\W/g, "_");
  const p = qsExtra() + "&stem=" + encodeURIComponent(stem);
  setStatus("保存中…", false);
  const res = await fetch("/api/save?" + p);
  const data = await res.json();
  if (!data.ok) {
    setStatus("保存失败：" + data.error, true);
    return;
  }
  const list = Object.entries(data.files)
    .map(([k, v]) => `${k}: ${v}`).join("\n");
  setStatus("已保存线性 16 位结果、掩码与独立预览：\n" + list, false);
}

$("sample-select").addEventListener("change", showSampleMeta);
$("btn-develop").addEventListener("click", develop);
$("btn-save").addEventListener("click", saveResults);
$("stage-image").addEventListener("click", (e) => {
  const img = e.currentTarget;
  const rect = img.getBoundingClientRect();
  const col = Math.floor((e.clientX - rect.left) / rect.width *
    (img.naturalWidth || 1));
  const row = Math.floor((e.clientY - rect.top) / rect.height *
    (img.naturalHeight || 1));
  inspectPixel(row, col);
});
$("auto-wb").addEventListener("change", () => {
  const disabled = $("auto-wb").checked;
  for (const id of ["gain-r", "gain-g", "gain-b"])
    $(id).disabled = disabled;
});

loadSamples();
