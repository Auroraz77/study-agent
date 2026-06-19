const runBtn = document.getElementById("runBtn");
const seedBtn = document.getElementById("seedBtn");
const uploadBtn = document.getElementById("uploadBtn");
const fileInput = document.getElementById("fileInput");
const statusPill = document.getElementById("statusPill");
const kbStatus = document.getElementById("kbStatus");
const refreshDashboardBtn = document.getElementById("refreshDashboardBtn");
const dashboardSearchBtn = document.getElementById("dashboardSearchBtn");
const dashboardStatus = document.getElementById("dashboardStatus");

let currentResources = [];
let dashboardLoaded = false;

runBtn.addEventListener("click", runWorkflow);
seedBtn.addEventListener("click", seedKnowledge);
uploadBtn.addEventListener("click", uploadKnowledge);
refreshDashboardBtn.addEventListener("click", loadDashboard);
dashboardSearchBtn.addEventListener("click", searchDashboardKnowledge);

document.querySelectorAll(".nav-btn").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

async function runWorkflow() {
  setStatus("running", "生成中");
  runBtn.disabled = true;

  const payload = {
    student_id: document.getElementById("studentId").value.trim() || "demo-student",
    course: document.getElementById("course").value.trim() || "机器学习",
    message: document.getElementById("message").value.trim(),
  };

  try {
    const result = await postJson("/api/learn", payload);
    renderResult(result);
    dashboardLoaded = false;
    setStatus("done", "已完成");
  } catch (error) {
    setStatus("error", "生成失败");
    document.getElementById("finalAnswer").textContent = error.message;
  } finally {
    runBtn.disabled = false;
  }
}

async function seedKnowledge() {
  setStatus("running", "导入中");
  try {
    const result = await postJson("/api/knowledge/seed", {});
    kbStatus.textContent = `演示资料已导入，当前知识片段 ${result.total} 条。`;
    dashboardLoaded = false;
    setStatus("done", "已导入");
  } catch (error) {
    kbStatus.textContent = error.message;
    setStatus("error", "导入失败");
  }
}

async function uploadKnowledge() {
  const file = fileInput.files[0];
  if (!file) {
    kbStatus.textContent = "请选择一个资料文件。";
    return;
  }

  const form = new FormData();
  form.append("file", file);
  form.append("course", document.getElementById("course").value.trim() || "机器学习");
  setStatus("running", "上传中");

  try {
    const response = await fetch("/api/knowledge/upload", {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const detail = await response.json();
      throw new Error(detail.detail || "上传失败");
    }
    const result = await response.json();
    if (result.parse_status === "parsed") {
      kbStatus.textContent = `${result.filename} 已上传到 MinIO，并切分为 ${result.chunks} 个知识片段。`;
    } else {
      kbStatus.textContent = `${result.filename} 已上传到 MinIO，但解析未完成：${result.message || result.parse_status}`;
    }
    dashboardLoaded = false;
    setStatus("done", "已上传");
  } catch (error) {
    kbStatus.textContent = error.message;
    setStatus("error", "上传失败");
  }
}

function renderResult(result) {
  document.getElementById("finalAnswer").textContent = result.final_answer || "已生成。";
  renderProfile(result.profile || {});
  renderContext(result.retrieved_context || []);
  renderResources(result.resources || []);
  renderPath(result.learning_path || {});

  document.getElementById("profileMetric").textContent = result.profile?.course || "已生成";
  document.getElementById("ragMetric").textContent = `${result.retrieved_context?.length || 0} 条`;
  document.getElementById("resourceMetric").textContent = `${result.resources?.length || 0} 类`;
  document.getElementById("pathMetric").textContent = result.learning_path?.stages ? "已生成" : "待完善";
}

function renderProfile(profile) {
  const container = document.getElementById("profileView");
  const entries = Object.entries(profile);
  if (!entries.length) {
    container.textContent = "暂无画像。";
    return;
  }

  container.innerHTML = entries
    .map(([key, value]) => {
      const rendered = Array.isArray(value) ? value.join("、") : String(value);
      return `
        <div class="profile-item">
          <span class="profile-key">${escapeHtml(key)}</span>
          <span class="profile-value">${escapeHtml(rendered)}</span>
        </div>
      `;
    })
    .join("");
}

function renderContext(items) {
  const container = document.getElementById("contextView");
  if (!items.length) {
    container.textContent = "暂无检索结果。";
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <div class="context-item">
          <strong>${escapeHtml(item.filename)} #${item.chunk_index}</strong>
          <p>${escapeHtml(item.text)}</p>
        </div>
      `,
    )
    .join("");
}

function renderResources(resources) {
  currentResources = resources;
  const tabs = document.getElementById("resourceTabs");
  const content = document.getElementById("resourceContent");

  if (!resources.length) {
    tabs.innerHTML = "";
    content.textContent = "暂无资源。";
    return;
  }

  tabs.innerHTML = resources
    .map(
      (resource, index) => `
        <button class="tab ${index === 0 ? "active" : ""}" data-index="${index}">
          ${escapeHtml(resource.title)}
        </button>
      `,
    )
    .join("");

  tabs.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      showResource(Number(tab.dataset.index));
    });
  });

  showResource(0);
}

function showResource(index) {
  const resource = currentResources[index];
  const container = document.getElementById("resourceContent");
  if (!resource) {
    container.textContent = "暂无资源。";
    return;
  }

  container.innerHTML = `
    <p><strong>${escapeHtml(resource.agent)}</strong>${resource.modality ? ` · <span class="resource-modality">${escapeHtml(resource.modality)}</span>` : ""}</p>
    <div id="resourceMedia"></div>
    ${markdownToHtml(resource.content || "")}
  `;
  renderResourceMedia(resource, document.getElementById("resourceMedia"));
  typesetMath(container);
}

function renderResourceMedia(resource, container) {
  if (!container || !resource?.media) return;

  if (resource.media.kind === "html_animation" && resource.media.html) {
    const frame = document.createElement("iframe");
    frame.className = "animation-frame";
    frame.title = resource.media.label || "教学动画";
    frame.loading = "lazy";
    frame.sandbox = "allow-scripts";
    frame.srcdoc = resource.media.html;
    container.appendChild(frame);
  }
}

function renderPath(path) {
  const container = document.getElementById("pathView");
  const stages = path.stages || [];
  if (!stages.length) {
    container.textContent = "暂无路径。";
    return;
  }

  container.innerHTML = stages
    .map((stage, index) => {
      const resources = Array.isArray(stage.resources) ? stage.resources.join("、") : "";
      return `
        <div class="stage">
          <strong>${index + 1}. ${escapeHtml(stage.name || "学习阶段")}</strong>
          <p>${escapeHtml(stage.goal || "")}</p>
          <p>${escapeHtml(resources)}</p>
        </div>
      `;
    })
    .join("");
}

function switchView(viewId) {
  document.querySelectorAll(".app-view").forEach((view) => {
    view.classList.toggle("hidden", view.id !== viewId);
    view.classList.toggle("active", view.id === viewId);
  });
  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewId);
  });
  document.querySelectorAll(".workspace-panel").forEach((panel) => {
    panel.classList.toggle("hidden", viewId !== "workspaceView");
  });
  document.querySelectorAll(".dashboard-panel").forEach((panel) => {
    panel.classList.toggle("hidden", viewId !== "dashboardView");
  });

  if (viewId === "dashboardView" && !dashboardLoaded) {
    loadDashboard();
  }
}

async function loadDashboard() {
  setDashboardStatus("running", "加载中");
  try {
    const [summary, files, profiles, resources, paths, events] = await Promise.all([
      getJson("/api/dashboard/summary"),
      getJson("/api/dashboard/files?limit=80"),
      getJson("/api/dashboard/profiles?limit=80"),
      getJson("/api/dashboard/resources?limit=80"),
      getJson("/api/dashboard/paths?limit=80"),
      getJson("/api/dashboard/events?limit=100"),
    ]);

    renderDashboardMetrics(summary);
    renderFilesTable(files.items || []);
    renderProfiles(profiles.items || []);
    renderResourceHistory(resources.items || []);
    renderPathHistory(paths.items || []);
    renderEventsTable(events.items || []);
    await searchDashboardKnowledge();

    dashboardLoaded = true;
    setDashboardStatus("done", "已刷新");
  } catch (error) {
    setDashboardStatus("error", "加载失败");
    document.getElementById("dashboardMetrics").innerHTML = `<div><strong>${escapeHtml(error.message)}</strong></div>`;
  }
}

function renderDashboardMetrics(summary) {
  const counts = summary.counts || {};
  const metrics = [
    ["课程数量", counts.courses],
    ["上传文件", counts.files],
    ["已解析文件", counts.parsed_files],
    ["知识切片", counts.knowledge_chunks],
    ["向量数量", counts.knowledge_embeddings],
    ["学生画像", counts.student_profiles],
    ["生成资源", counts.generated_resources],
    ["学习事件", counts.learning_events],
  ];

  document.getElementById("dashboardMetrics").innerHTML = metrics
    .map(
      ([label, value]) => `
        <div>
          <span class="metric-label">${escapeHtml(label)}</span>
          <strong>${escapeHtml(value ?? 0)}</strong>
        </div>
      `,
    )
    .join("");
}

function renderFilesTable(items) {
  const tbody = document.getElementById("filesTable");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="8">暂无课程资料。</td></tr>`;
    return;
  }

  tbody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.id)}</td>
          <td>${escapeHtml(item.course)}</td>
          <td>${escapeHtml(item.filename)}</td>
          <td>${escapeHtml(shortType(item.file_type))}</td>
          <td>${escapeHtml(formatBytes(item.file_size))}</td>
          <td><span class="status-tag ${statusClass(item.parse_status)}">${escapeHtml(item.parse_status)}</span></td>
          <td>${escapeHtml(item.chunk_count || 0)}</td>
          <td class="clip-cell" title="${escapeHtml(item.object_name || "")}">${escapeHtml(item.object_name || "-")}</td>
        </tr>
      `,
    )
    .join("");
}

function renderProfiles(items) {
  const container = document.getElementById("profilesList");
  if (!items.length) {
    container.textContent = "暂无学生画像。";
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <article class="record-item">
          <div class="record-title">
            <strong>${escapeHtml(item.student_id)}</strong>
            <span>${escapeHtml(item.course)}</span>
          </div>
          <p>${escapeHtml(item.learning_goal || "暂无学习目标")}</p>
          <p><b>基础：</b>${escapeHtml(item.knowledge_base || "-")}</p>
          <p><b>薄弱点：</b>${escapeHtml((item.weaknesses || []).join("、") || "-")}</p>
          <p><b>偏好：</b>${escapeHtml((item.learning_style || []).join("、") || "-")}</p>
          <small>${escapeHtml(item.updated_at || "")}</small>
        </article>
      `,
    )
    .join("");
}

function renderResourceHistory(items) {
  const container = document.getElementById("resourcesList");
  if (!items.length) {
    container.textContent = "暂无生成资源。";
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <article class="record-item">
          <div class="record-title">
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(item.resource_type)}</span>
          </div>
          <p>${escapeHtml(item.student_id)} · ${escapeHtml(item.course)} · ${escapeHtml(item.agent || "-")}</p>
          <p>${escapeHtml(item.content_preview || "")}</p>
          <small>${escapeHtml(item.created_at || "")}</small>
        </article>
      `,
    )
    .join("");
}

function renderPathHistory(items) {
  const container = document.getElementById("pathsList");
  if (!items.length) {
    container.textContent = "暂无学习路径。";
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <article class="record-item">
          <div class="record-title">
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(item.status)}</span>
          </div>
          <p>${escapeHtml(item.student_id)} · ${escapeHtml(item.course)} · ${escapeHtml(item.stage_count)} 个阶段</p>
          <p>${escapeHtml((item.path_json?.stages || []).map((stage) => stage.name).join(" → ") || "-")}</p>
          <small>${escapeHtml(item.created_at || "")}</small>
        </article>
      `,
    )
    .join("");
}

function renderEventsTable(items) {
  const tbody = document.getElementById("eventsTable");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="6">暂无学习行为日志。</td></tr>`;
    return;
  }

  tbody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.id)}</td>
          <td>${escapeHtml(item.student_id)}</td>
          <td>${escapeHtml(item.course)}</td>
          <td>${escapeHtml(item.event_type)}</td>
          <td>${escapeHtml(item.created_at || "")}</td>
          <td class="clip-cell">${escapeHtml(JSON.stringify(item.event_data || {}))}</td>
        </tr>
      `,
    )
    .join("");
}

async function searchDashboardKnowledge() {
  const query = document.getElementById("dashboardSearchInput").value.trim();
  const container = document.getElementById("dashboardSearchResults");
  if (!query) {
    container.textContent = "请输入检索关键词。";
    return;
  }

  try {
    const result = await postJson("/api/knowledge/search", {query, top_k: 8});
    const items = result.items || [];
    if (!items.length) {
      container.textContent = "暂无检索结果。";
      return;
    }
    container.innerHTML = items
      .map(
        (item) => `
          <div class="context-item">
            <strong>${escapeHtml(item.filename)} #${escapeHtml(item.chunk_index)} · score ${escapeHtml(item.score ?? "-")}</strong>
            <p>${escapeHtml(item.text)}</p>
          </div>
        `,
      )
      .join("");
  } catch (error) {
    container.textContent = error.message;
  }
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

function setStatus(type, text) {
  statusPill.className = `status-pill ${type}`;
  statusPill.textContent = text;
}

function setDashboardStatus(type, text) {
  dashboardStatus.className = `status-pill ${type}`;
  dashboardStatus.textContent = text;
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const codeBlocks = [];
  const html = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim();
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1;
      if (lang.toLowerCase() === "mermaid" && code.some((item) => item.trim() === "mindmap")) {
        html.push(renderMindmap(code.join("\n")));
        continue;
      }
      const cls = lang ? ` class="language-${escapeHtml(lang)}"` : "";
      codeBlocks.push(`<pre><code${cls}>${escapeHtml(code.join("\n"))}</code></pre>`);
      html.push(codeBlocks[codeBlocks.length - 1]);
      continue;
    }

    if (trimmed.startsWith("$$")) {
      const math = [];
      const first = trimmed.slice(2);
      if (first.endsWith("$$") && first.length > 2) {
        math.push(first.slice(0, -2));
        i += 1;
      } else {
        if (first) math.push(first);
        i += 1;
        while (i < lines.length && !lines[i].trim().endsWith("$$")) {
          math.push(lines[i]);
          i += 1;
        }
        if (i < lines.length) {
          math.push(lines[i].trim().slice(0, -2));
          i += 1;
        }
      }
      html.push(`<div class="math-block">\\[${escapeHtml(math.join("\n"))}\\]</div>`);
      continue;
    }

    if (isTableStart(lines, i)) {
      const tableLines = [lines[i], lines[i + 1]];
      i += 2;
      while (i < lines.length && isTableRow(lines[i])) {
        tableLines.push(lines[i]);
        i += 1;
      }
      html.push(renderTable(tableLines));
      continue;
    }

    if (/^#{1,4}\s+/.test(trimmed)) {
      const level = Math.min(trimmed.match(/^#+/)[0].length, 4);
      const text = trimmed.replace(/^#{1,4}\s+/, "");
      html.push(`<h${level}>${renderInline(text)}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*+]\s+/, ""));
        i += 1;
      }
      html.push(`<ul>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      html.push(`<ol>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`);
      continue;
    }

    const paragraph = [trimmed];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines, i)) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
  }

  return html.join("");
}

function renderMindmap(source) {
  const lines = String(source || "")
    .split("\n")
    .filter((line) => line.trim() && line.trim() !== "mindmap");
  const stack = [];
  let root = null;

  lines.forEach((line) => {
    const indent = line.match(/^\s*/)?.[0].length || 0;
    const node = {label: cleanMindmapLabel(line.trim()), children: []};
    while (stack.length && stack[stack.length - 1].indent >= indent) {
      stack.pop();
    }
    if (!stack.length) {
      root = node;
    } else {
      stack[stack.length - 1].node.children.push(node);
    }
    stack.push({indent, node});
  });

  if (!root) {
    return `<pre><code>${escapeHtml(source)}</code></pre>`;
  }

  return `
    <div class="mindmap-view">
      <div class="mindmap-root">${escapeHtml(root.label)}</div>
      ${renderMindmapChildren(root.children)}
    </div>
  `;
}

function renderMindmapChildren(children) {
  if (!children.length) return "";
  return `
    <ul>
      ${children
        .map(
          (child) => `
            <li>
              <span>${escapeHtml(child.label)}</span>
              ${renderMindmapChildren(child.children)}
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function cleanMindmapLabel(label) {
  return label
    .replace(/^root\s*/i, "")
    .replace(/^\(\(/, "")
    .replace(/\)\)$/, "")
    .replace(/^\[/, "")
    .replace(/\]$/, "")
    .trim();
}

function isBlockStart(lines, index) {
  const trimmed = lines[index].trim();
  return (
    trimmed.startsWith("```") ||
    trimmed.startsWith("$$") ||
    /^#{1,4}\s+/.test(trimmed) ||
    /^[-*+]\s+/.test(trimmed) ||
    /^\d+\.\s+/.test(trimmed) ||
    isTableStart(lines, index)
  );
}

function isTableStart(lines, index) {
  return (
    index + 1 < lines.length &&
    isTableRow(lines[index]) &&
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])
  );
}

function isTableRow(line) {
  return line.includes("|") && line.trim().replace(/\|/g, "").trim().length > 0;
}

function renderTable(tableLines) {
  const header = splitTableRow(tableLines[0]);
  const rows = tableLines.slice(2).map(splitTableRow);

  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>${header.map((cell) => `<th>${renderInline(cell)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${rows
            .map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`)
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderInline(text) {
  const placeholders = [];
  let source = String(text || "");

  source = source.replace(/`([^`]+)`/g, (_, code) => {
    placeholders.push(`<code>${escapeHtml(code)}</code>`);
    return `@@INLINE_${placeholders.length - 1}@@`;
  });

  source = source.replace(/\\\((.+?)\\\)/g, (_, formula) => {
    placeholders.push(`<span class="math-inline">\\(${escapeHtml(formula)}\\)</span>`);
    return `@@INLINE_${placeholders.length - 1}@@`;
  });

  source = source.replace(/\$([^$\n]+)\$/g, (_, formula) => {
    placeholders.push(`<span class="math-inline">\\(${escapeHtml(formula)}\\)</span>`);
    return `@@INLINE_${placeholders.length - 1}@@`;
  });

  let rendered = escapeHtml(source)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");

  placeholders.forEach((value, index) => {
    rendered = rendered.replace(`@@INLINE_${index}@@`, value);
  });

  return rendered;
}

function typesetMath(container) {
  if (window.MathJax?.typesetPromise) {
    window.MathJax.typesetPromise([container]).catch(() => {});
  }
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function shortType(type) {
  return String(type || "-")
    .replace("application/vnd.openxmlformats-officedocument.", "")
    .replace("wordprocessingml.document", "docx")
    .replace("presentationml.presentation", "pptx")
    .replace("application/", "");
}

function statusClass(status) {
  if (status === "parsed") return "ok";
  if (status === "parse_failed") return "bad";
  return "warn";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
