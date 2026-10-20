"use strict";

const state = { status: null, windows: [], currentTree: null, flameRoot: null };
const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 1) => value == null ? "未知" : Number(value).toFixed(digits);
const bytes = (value) => {
  if (value == null) return "未知";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let number = Number(value), index = 0;
  while (number >= 1024 && index < units.length - 1) { number /= 1024; index += 1; }
  return `${number.toFixed(index ? 1 : 0)} ${units[index]}`;
};
const api = async (path, options = {}) => {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || response.statusText);
  return value;
};

function renderStatus(value) {
  state.status = value;
  const live = value.service?.live;
  $("live-dot").className = `dot ${live ? "live" : "bad"}`;
  $("live-label").textContent = live ? "实时数据有效" : "数据已停止或过期";
  const stale = $("stale-banner");
  const captureLive = value.capture?.live;
  if (!live || (value.capture?.available && !captureLive)) {
    stale.classList.remove("hidden");
    stale.textContent = !live ? "观测后端没有持续更新；下方数据可能是旧快照。" : value.capture.stale_reason;
  } else stale.classList.add("hidden");

  $("game-date").textContent = value.capture?.game_date || "未知";
  const progress = value.game_progress || {};
  $("game-speed").textContent = progress.available
    ? `${fmt(progress.seconds_per_game_year)} 秒 / 游戏年 · ${fmt(progress.game_days_per_real_second, 2)} 游戏日/秒`
    : progress.reason || "等待推进数据";
  const process = value.process || {};
  $("game-process").textContent = process.available ? `PID ${process.pid}` : "未发现";
  $("game-memory").textContent = process.available
    ? `CPU ${fmt(process.cpu_percent)}% · RSS ${bytes(process.rss_bytes)} · ${process.thread_count} threads`
    : process.reason || "无进程数据";
  const totals = value.capture?.totals || {};
  $("capture-total").textContent = Number(totals.command_records || 0).toLocaleString();
  const lost = Number(totals.dropped || 0) + Number(totals.writer_dropped || 0);
  const backlog = value.capture?.backlog || {};
  $("capture-health").textContent = `类型 ${totals.command_types || 0} · 丢失 ${lost} · 积压 ${bytes((backlog.ready_bytes || 0) + (backlog.unread_bytes || 0))}`;
  const profiler = value.profiler || {};
  $("profiler-state").textContent = String(profiler.state || "unknown").toUpperCase();
  $("profiler-detail").textContent = profiler.last_error || profiler.availability?.reason || `最近窗口 ${profiler.last_window || "无"}`;
  renderThreads(process.threads || []);
  renderCommandDiff(value.capture?.command_diff || {});
}

function renderThreads(threads) {
  const target = $("thread-list");
  if (!threads.length) { target.className = "thread-list empty"; target.textContent = "暂无线程数据"; return; }
  target.className = "thread-list";
  const max = Math.max(1, ...threads.map((item) => item.cpu_percent_one_core || 0));
  target.innerHTML = threads.slice(0, 18).map((item) => `
    <div class="thread-row"><span>${escapeHtml(item.name || `tid:${item.tid}`)}</span>
      <strong>${item.cpu_percent_one_core == null ? "warming" : fmt(item.cpu_percent_one_core) + "%"}</strong>
      <span class="bar"><i style="width:${100 * (item.cpu_percent_one_core || 0) / max}%"></i></span></div>`).join("");
}

function renderCommandDiff(diff) {
  const target = $("command-diff");
  if (!diff.baseline_configured) { target.className = "empty"; target.textContent = "未配置原版 catalog 基线；不会猜测 Mod 来源。"; return; }
  target.className = "diff-list";
  const section = (title, values) => `<div><h3>${title} (${values.length})</h3><div class="chips">${values.length ? values.slice(0, 80).map((v) => `<span class="chip">${escapeHtml(v)}</span>`).join("") : "无"}</div></div>`;
  target.innerHTML = section("新增命令 RTTI", diff.new_command_types || [])
    + section("新增嵌套类型", diff.new_nested_types || [])
    + section("新增 Payload 类型", diff.new_payload_types || [])
    + section("命令结构变化候选", (diff.changed_command_layouts || []).map((item) => item.type));
}

async function refreshStatus() {
  try { renderStatus(await api("/api/status")); } catch (error) {
    $("live-dot").className = "dot bad"; $("live-label").textContent = `后端错误: ${error.message}`;
  }
}

async function refreshWindows() {
  const value = await api("/api/windows?limit=160");
  state.windows = value.windows || [];
  const options = state.windows.map((window) => `<option value="${window.id}">${window.game_date || "无日期"} · ${window.started_at} · ${window.sample_count} samples</option>`).join("");
  for (const id of ["window-select", "baseline-select", "comparison-select"]) {
    const select = $(id), previous = select.value;
    select.innerHTML = options;
    if (state.windows.some((window) => window.id === previous)) select.value = previous;
  }
  if (state.windows.length > 1 && $("baseline-select").selectedIndex === 0) $("baseline-select").selectedIndex = 1;
  if (state.windows.length) await loadWindow();
}

async function loadWindow() {
  const windowId = $("window-select").value;
  if (!windowId) { $("profile-unavailable").classList.remove("hidden"); $("profile-content").classList.add("hidden"); return; }
  const metadata = await api(`/api/windows/${encodeURIComponent(windowId)}`);
  const threadSelect = $("thread-select"), previous = threadSelect.value;
  const hasMain = (metadata.threads || []).some((thread) => thread.role === "main");
  const hasWorkers = (metadata.threads || []).some((thread) => thread.role !== "main");
  threadSelect.innerHTML = `<option value="all">全进程</option>`
    + (hasMain ? `<option value="main">主线程</option>` : "")
    + (hasWorkers ? `<option value="workers">所有非主线程</option>` : "")
    + (metadata.threads || []).map((thread) => `<option value="${thread.key}">${escapeHtml(thread.comm)} · tid ${thread.tid} · ${thread.sample_count}</option>`).join("");
  if ([...threadSelect.options].some((option) => option.value === previous)) threadSelect.value = previous;
  await loadProfileData();
}

async function loadProfileData() {
  const windowId = $("window-select").value, thread = $("thread-select").value, sort = $("sort-select").value;
  if (!windowId) return;
  const [hotspots, tree] = await Promise.all([
    api(`/api/windows/${encodeURIComponent(windowId)}/hotspots?thread=${encodeURIComponent(thread)}&sort=${sort}`),
    api(`/api/windows/${encodeURIComponent(windowId)}/flame?thread=${encodeURIComponent(thread)}`),
  ]);
  $("profile-unavailable").classList.add("hidden"); $("profile-content").classList.remove("hidden");
  $("hotspot-body").innerHTML = (hotspots.hotspots || []).slice(0, 120).map((item) => `<tr><td>${escapeHtml(item.symbol)}</td><td>${escapeHtml(item.module)}</td><td>${fmt(item.self_percent, 2)}%<br><small>${item.self_samples} samples</small></td><td>${fmt(item.inclusive_percent, 2)}%<br><small>${item.inclusive_samples} samples</small></td><td>${fmt(sort === "inclusive" ? item.inclusive_cpu_seconds_estimate : item.self_cpu_seconds_estimate, 3)}</td></tr>`).join("");
  state.currentTree = tree; state.flameRoot = tree; $("flame-path").textContent = tree.name; renderFlame(tree, $("flame-svg"), $("flame-tip"), false);
}

function nodeWeight(node, diff) { return diff ? Math.max(node.baseline_samples || 0, node.comparison_samples || 0) : node.samples || 0; }
function colorFor(node, diff) {
  if (diff) { const delta = node.delta_samples || 0; return delta > 0 ? `hsl(5 65% ${Math.max(30, 58 - Math.min(24, delta))}%)` : delta < 0 ? `hsl(170 55% ${Math.max(28, 54 - Math.min(20, -delta))}%)` : "#50605d"; }
  let hash = 0; for (const char of (node.module || node.name)) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return `hsl(${165 + Math.abs(hash) % 70} 48% ${36 + Math.abs(hash >> 8) % 18}%)`;
}

function renderFlame(root, svg, tip, diff) {
  const width = Math.max(900, svg.parentElement.clientWidth - 2), row = 24, nodes = [];
  const walk = (node, x, y, w, path) => {
    nodes.push({node, x, y, w, path}); const total = Math.max(1, nodeWeight(node, diff)); let offset = x;
    for (const child of node.children || []) { const childWidth = w * nodeWeight(child, diff) / total; if (childWidth >= .5) walk(child, offset, y + row, childWidth, path.concat(child)); offset += childWidth; }
  };
  walk(root, 0, 0, width, [root]); const height = Math.max(90, ...nodes.map((item) => item.y + row));
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`); svg.setAttribute("width", width); svg.setAttribute("height", height); svg.innerHTML = "";
  for (const item of nodes) {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g"), rect = document.createElementNS(group.namespaceURI, "rect"), text = document.createElementNS(group.namespaceURI, "text");
    rect.setAttribute("x", item.x + .5); rect.setAttribute("y", item.y + .5); rect.setAttribute("width", Math.max(0, item.w - 1)); rect.setAttribute("height", row - 1); rect.setAttribute("fill", colorFor(item.node, diff)); rect.setAttribute("stroke", "#06100f");
    text.setAttribute("x", item.x + 4); text.setAttribute("y", item.y + 16); text.setAttribute("fill", "#e7f3f1"); text.setAttribute("font-size", "11"); text.textContent = item.w > 70 ? item.node.name.slice(0, Math.floor(item.w / 7)) : "";
    group.append(rect, text); group.addEventListener("mousemove", (event) => { tip.classList.remove("hidden"); tip.style.left = `${event.clientX + 12}px`; tip.style.top = `${event.clientY + 12}px`; tip.textContent = diff ? `${item.node.name}\n${item.node.module || ""}\n基线 ${item.node.baseline_samples || 0} / 对比 ${item.node.comparison_samples || 0} / Δ ${item.node.delta_samples || 0}` : `${item.node.name}\n${item.node.module || ""}\nInclusive ${item.node.samples || 0} samples · Self ${item.node.self_samples || 0}`; });
    group.addEventListener("mouseleave", () => tip.classList.add("hidden"));
    if (!diff && item.node.children?.length) group.addEventListener("click", () => { state.flameRoot = item.node; $("flame-path").textContent = item.path.map((v) => v.name).join(" › "); renderFlame(item.node, svg, tip, false); });
    svg.appendChild(group);
  }
}

async function compareWindows() {
  const baseline = $("baseline-select").value, comparison = $("comparison-select").value, thread = $("thread-select").value || "all";
  if (!baseline || !comparison) return;
  const tree = await api(`/api/compare?baseline=${encodeURIComponent(baseline)}&comparison=${encodeURIComponent(comparison)}&thread=${encodeURIComponent(thread)}`);
  renderFlame(tree, $("diff-svg"), $("diff-tip"), true);
}

function drawLines(canvas, series) {
  const ctx = canvas.getContext("2d"), width = canvas.width, height = canvas.height; ctx.clearRect(0, 0, width, height); ctx.fillStyle = "#071716"; ctx.fillRect(0, 0, width, height);
  for (const line of series) { const values = line.values.filter((v) => v != null && Number.isFinite(v)); if (values.length < 2) continue; const max = Math.max(...values, 1), min = Math.min(...values, 0); ctx.beginPath(); ctx.strokeStyle = line.color; ctx.lineWidth = 2; line.values.forEach((value, index) => { if (value == null) return; const x = 12 + index * (width - 24) / Math.max(1, line.values.length - 1), y = height - 14 - (value - min) * (height - 28) / Math.max(.0001, max - min); if (!index) ctx.moveTo(x, y); else ctx.lineTo(x, y); }); ctx.stroke(); }
}

async function refreshHistory() {
  const {history} = await api("/api/history?limit=300");
  drawLines($("history-chart"), [
    {color: "#5ce1d0", values: history.map((item) => item.process_cpu_percent)},
    {color: "#e2b85b", values: history.map((item) => item.seconds_per_game_year)},
  ]);
  const hot = await api(`/api/hotspot-history?limit=60&top=6&thread=${encodeURIComponent($("thread-select").value || "all")}`);
  const colors = ["#5ce1d0", "#e2b85b", "#ef6a6a", "#72dc96", "#a899ff", "#ff9bd2"];
  drawLines($("hotspot-chart"), hot.series.map((entry, index) => ({color: colors[index], values: hot.points.map((point) => point.values[entry.frame_id]?.inclusive_cpu_seconds_estimate || 0)})));
}

async function refreshMods() {
  const value = await api("/api/mods"), inventory = value.inventory;
  if (!inventory) { $("mod-summary").className = "empty"; $("mod-summary").textContent = value.scanning ? "正在扫描外部 Mod 文件" : "尚无 Mod 清单"; return; }
  const launcher = inventory.launcher_configuration || {}, save = inventory.save_evidence || {};
  $("mod-summary").className = "note"; $("mod-summary").textContent = `ELF ${inventory.elf_build_id || "未知"} · 启动器 ${launcher.enabled_mods_in_load_order?.length || 0} 个 · 存档证据 ${save.available ? save.declared_mods.length + " 个" : "不可用"}。外部定义不等同引擎实际加载定义。`;
  $("mod-list").innerHTML = (inventory.mods || []).map((mod) => `<div class="mod-card"><strong>${mod.load_index + 1}. ${escapeHtml(mod.name || mod.launcher_entry)}</strong><br><small>${escapeHtml((mod.tags || []).join(", "))} · ${escapeHtml(mod.supported_version || "版本未知")}</small><br><code>semantic ${escapeHtml(mod.fingerprints?.semantic_content_fingerprint_sha256?.slice(0, 20) || "unavailable")} · ${mod.external_definitions?.files_scanned || 0} definitions files</code></div>`).join("");
}

function escapeHtml(value) { const span = document.createElement("span"); span.textContent = String(value ?? ""); return span.innerHTML; }

document.querySelectorAll("button[data-action]").forEach((button) => button.addEventListener("click", async () => { try { await api(`/api/profiler/${button.dataset.action}`, {method: "POST"}); await refreshStatus(); } catch (error) { alert(error.message); } }));
$("window-select").addEventListener("change", loadWindow); $("thread-select").addEventListener("change", async () => { await loadProfileData(); await refreshHistory(); }); $("sort-select").addEventListener("change", loadProfileData);
$("flame-reset").addEventListener("click", () => { if (state.currentTree) { state.flameRoot = state.currentTree; $("flame-path").textContent = state.currentTree.name; renderFlame(state.currentTree, $("flame-svg"), $("flame-tip"), false); } });
$("compare-button").addEventListener("click", compareWindows); $("refresh-mods").addEventListener("click", async () => { await api("/api/mods/refresh", {method: "POST"}); setTimeout(refreshMods, 1000); });

Promise.all([refreshStatus(), refreshWindows(), refreshHistory(), refreshMods()]).catch(console.error);
setInterval(refreshStatus, 3000); setInterval(refreshWindows, 15000); setInterval(refreshHistory, 60000); setInterval(refreshMods, 60000);
