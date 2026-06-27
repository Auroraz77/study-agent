const runBtn = document.getElementById("runBtn");
const seedBtn = document.getElementById("seedBtn");
const uploadBtn = document.getElementById("uploadBtn");
const fileInput = document.getElementById("fileInput");
const statusPill = document.getElementById("statusPill");
const kbStatus = document.getElementById("kbStatus");
const refreshDashboardBtn = document.getElementById("refreshDashboardBtn");
const dashboardSearchBtn = document.getElementById("dashboardSearchBtn");
const dashboardStatus = document.getElementById("dashboardStatus");
const askBtn = document.getElementById("askBtn");
const qaQuestion = document.getElementById("qaQuestion");
const qaHistory = document.getElementById("qaHistory");
const qaResizeHandle = document.getElementById("qaResizeHandle");
const qaModeButtons = document.querySelectorAll(".qa-mode-option");
const qaModeTrigger = document.getElementById("qaModeTrigger");
const qaModeMenu = document.getElementById("qaModeMenu");
const qaModeLabel = document.getElementById("qaModeLabel");
const loginBtn = document.getElementById("loginBtn");
const registerBtn = document.getElementById("registerBtn");
const logoutBtn = document.getElementById("logoutBtn");
const accountTrigger = document.getElementById("accountTrigger");
const accountMenu = document.getElementById("accountMenu");
const accountName = document.getElementById("accountName");
const accountStudentId = document.getElementById("accountStudentId");
const authModal = document.getElementById("authModal");
const authCloseBtn = document.getElementById("authCloseBtn");
const authTitle = document.getElementById("authTitle");
const authInfo = document.getElementById("authInfo");
const authUsername = document.getElementById("authUsername");
const authPassword = document.getElementById("authPassword");
const authStudentId = document.getElementById("authStudentId");

let currentResources = [];
let dashboardLoaded = false;
let authToken = localStorage.getItem("learning_auth_token") || "";
let currentUser = null;
let qaMode = localStorage.getItem("learning_qa_mode") || "rag";
let currentSpeechAudio = null;

runBtn.addEventListener("click", runWorkflow);
seedBtn.addEventListener("click", seedKnowledge);
uploadBtn.addEventListener("click", uploadKnowledge);
refreshDashboardBtn.addEventListener("click", loadDashboard);
dashboardSearchBtn.addEventListener("click", searchDashboardKnowledge);
askBtn.addEventListener("click", askQuestion);
qaModeTrigger.addEventListener("click", toggleQaModeMenu);
qaModeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setQaMode(button.dataset.mode || "rag");
    closeQaModeMenu();
  });
});
loginBtn.addEventListener("click", login);
registerBtn.addEventListener("click", register);
logoutBtn.addEventListener("click", logout);
accountTrigger.addEventListener("click", toggleAccount);
authCloseBtn.addEventListener("click", closeAuthModal);
authModal.addEventListener("click", (event) => {
  if (event.target === authModal) {
    closeAuthModal();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeAuthModal();
    accountMenu.classList.add("hidden");
    closeQaModeMenu();
  }
});
document.addEventListener("click", (event) => {
  if (!qaModeMenu?.contains(event.target) && !qaModeTrigger?.contains(event.target)) {
    closeQaModeMenu();
  }
});

document.querySelectorAll(".nav-btn").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

restoreSession();
moveLearningInfoToSidebar();
initQaResize();
setQaMode(qaMode);
document.getElementById("contextView")?.closest(".section-block")?.classList.add("hidden");

function moveLearningInfoToSidebar() {
  const knowledgePanel = kbStatus.closest(".panel");
  const profilePanel = document.getElementById("profileView")?.closest(".section-block");
  const pathPanel = document.getElementById("pathView")?.closest(".section-block");
  if (!knowledgePanel || !profilePanel || !pathPanel) return;

  [profilePanel, pathPanel].forEach((panel) => {
    panel.classList.add("workspace-panel", "sidebar-info-panel");
  });
  knowledgePanel.after(profilePanel);
  profilePanel.after(pathPanel);
}

function initQaResize() {
  const grid = document.querySelector(".content-grid");
  if (!grid || !qaResizeHandle) return;

  const savedWidth = Number(localStorage.getItem("learning_qa_width") || 0);
  if (savedWidth) {
    grid.style.setProperty("--qa-width", `${savedWidth}px`);
  }

  let dragging = false;
  qaResizeHandle.addEventListener("pointerdown", (event) => {
    dragging = true;
    qaResizeHandle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing-qa");
  });

  qaResizeHandle.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const rect = grid.getBoundingClientRect();
    const minWidth = 360;
    const maxWidth = Math.min(760, Math.max(minWidth, rect.width * 0.55));
    const width = Math.round(Math.min(maxWidth, Math.max(minWidth, rect.right - event.clientX)));
    grid.style.setProperty("--qa-width", `${width}px`);
    localStorage.setItem("learning_qa_width", String(width));
  });

  qaResizeHandle.addEventListener("pointerup", (event) => {
    dragging = false;
    qaResizeHandle.releasePointerCapture(event.pointerId);
    document.body.classList.remove("resizing-qa");
  });
}

function setQaMode(mode) {
  qaMode = mode === "llm" ? "llm" : "rag";
  localStorage.setItem("learning_qa_mode", qaMode);
  if (qaModeLabel) {
    qaModeLabel.textContent = qaMode === "llm" ? "直接问AI" : "结合知识库";
  }
  qaModeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === qaMode);
  });
}

function toggleQaModeMenu() {
  const isHidden = qaModeMenu.classList.toggle("hidden");
  qaModeTrigger.setAttribute("aria-expanded", String(!isHidden));
}

function closeQaModeMenu() {
  qaModeMenu?.classList.add("hidden");
  qaModeTrigger?.setAttribute("aria-expanded", "false");
}

async function runWorkflow() {
  if (!requireLogin()) return;
  setStatus("running", "生成中");
  runBtn.disabled = true;

  const payload = {
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
      headers: authHeaders(false),
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

async function askQuestion() {
  if (!requireLogin()) return;
  const question = qaQuestion.value.trim();
  if (!question) {
    qaQuestion.focus();
    return;
  }

  askBtn.disabled = true;
  askBtn.textContent = "回答中";
  appendQaMessage({
    question,
    answer: qaMode === "rag" ? "正在检索课程资料并生成回答..." : "正在直接请求 AI 生成回答...",
    pending: true,
    mode: qaMode,
  });

  try {
    const result = await postJson("/api/qa/ask", {
      course: document.getElementById("course").value.trim() || "机器学习",
      question,
      learning_context: qaMode === "rag" ? document.getElementById("message").value.trim() : "",
      mode: qaMode,
    });
    updateLastQaMessage({
      question,
      answer: result.answer || "暂无回答。",
      context: result.retrieved_context || [],
      mode: result.mode || qaMode,
    });
    qaQuestion.value = "";
    dashboardLoaded = false;
  } catch (error) {
    updateLastQaMessage({
      question,
      answer: error.message,
      error: true,
      mode: qaMode,
    });
  } finally {
    askBtn.disabled = false;
    askBtn.textContent = "提问";
  }
}

function appendQaMessage(entry) {
  qaHistory.querySelector(".qa-empty")?.remove();
  const item = document.createElement("article");
  item.className = `qa-message ${entry.pending ? "pending" : ""}`;
  item.innerHTML = renderQaMessage(entry);
  qaHistory.appendChild(item);
  qaHistory.scrollTop = qaHistory.scrollHeight;
}

function updateLastQaMessage(entry) {
  const item = qaHistory.querySelector(".qa-message:last-child");
  if (!item) {
    appendQaMessage(entry);
    return;
  }
  item.className = `qa-message ${entry.error ? "error" : ""}`;
  item.innerHTML = renderQaMessage(entry);
  typesetMath(item);
  qaHistory.scrollTop = qaHistory.scrollHeight;
}

function renderQaMessage(entry) {
  const modeLabel = entry.mode === "llm" ? "直接问AI" : "结合知识库";
  const sources =
    Array.isArray(entry.context) && entry.context.length
      ? `
        <details class="qa-sources">
          <summary>查看依据片段（${entry.context.length}）</summary>
          ${entry.context
            .map(
              (item) => `
                <div class="context-item">
                  <strong>${escapeHtml(item.filename || "课程资料")} #${escapeHtml(item.chunk_index ?? "-")}</strong>
                  <p>${escapeHtml(item.text || "")}</p>
                </div>
              `,
            )
            .join("")}
        </details>
      `
      : "";
  return `
    <div class="qa-turn qa-turn-user">
      <div class="qa-bubble qa-bubble-user">
        <div>${escapeHtml(entry.question || "")}</div>
      </div>
      <div class="qa-avatar user-avatar"></div>
    </div>
    <div class="qa-turn qa-turn-assistant">
      <div class="qa-avatar assistant-avatar">AI</div>
      <div class="qa-assistant-wrap">
        <span class="qa-speaker">AI助教 · ${escapeHtml(modeLabel)}</span>
        <div class="qa-bubble qa-bubble-assistant">
          <div class="qa-answer">${markdownToHtml(entry.answer || "")}</div>
          ${sources}
        </div>
      </div>
    </div>
  `;
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
  stopSpeech(false);
  if (!resource) {
    container.textContent = "暂无资源。";
    return;
  }

  container.innerHTML = `
    <p><strong>${escapeHtml(resource.agent)}</strong>${resource.modality ? ` · <span class="resource-modality">${escapeHtml(resource.modality)}</span>` : ""}</p>
    ${isSpeechResource(resource) ? renderSpeechControls() : ""}
    ${resource.type === "quiz" && Array.isArray(resource.quiz) ? "" : markdownToHtml(resource.content || "")}
    ${resource.type === "quiz" && Array.isArray(resource.quiz) ? renderQuizForm(resource.quiz) : ""}
  `;
  if (resource.type === "quiz" && Array.isArray(resource.quiz)) {
    bindQuizForm(resource);
  }
  if (isSpeechResource(resource)) {
    bindSpeechControls(resource);
  }
  typesetMath(container);
}

function isSpeechResource(resource) {
  const type = String(resource?.type || "").toLowerCase();
  const modality = String(resource?.modality || "").toLowerCase();
  const title = String(resource?.title || "");
  return type === "text" || type === "explanation_doc" || modality === "text" || title.includes("讲解文档");
}

function renderSpeechControls() {
  return `
    <section class="tts-panel">
      <div class="tts-copy">
        <strong>语音播报</strong>
        <span id="ttsStatus">使用 qwen3-tts-flash 生成讲解音频</span>
      </div>
      <div class="tts-actions">
        <button id="ttsPlayBtn" type="button" class="secondary-btn">生成并播放</button>
        <button id="ttsPauseBtn" type="button" class="secondary-btn" disabled>暂停</button>
        <button id="ttsResumeBtn" type="button" class="secondary-btn" disabled>继续</button>
        <button id="ttsStopBtn" type="button" class="secondary-btn" disabled>停止</button>
      </div>
    </section>
  `;
}

function bindSpeechControls(resource) {
  const playBtn = document.getElementById("ttsPlayBtn");
  const pauseBtn = document.getElementById("ttsPauseBtn");
  const resumeBtn = document.getElementById("ttsResumeBtn");
  const stopBtn = document.getElementById("ttsStopBtn");
  const status = document.getElementById("ttsStatus");
  if (!playBtn || !pauseBtn || !resumeBtn || !stopBtn || !status) return;

  playBtn.addEventListener("click", async () => {
    if (!requireLogin()) return;
    const text = extractSpeechText(resource);
    if (!text) {
      status.textContent = "当前讲解文档没有可播报内容";
      return;
    }

    playBtn.disabled = true;
    status.textContent = "正在生成语音...";
    try {
      const result = await postJson("/api/tts/speech", {text});
      stopSpeech(false);
      currentSpeechAudio = new Audio(`data:${result.content_type};base64,${result.audio_base64}`);
      currentSpeechAudio.addEventListener("ended", () => {
        status.textContent = "播报已结束";
        pauseBtn.disabled = true;
        resumeBtn.disabled = true;
        stopBtn.disabled = true;
      });
      await currentSpeechAudio.play();
      status.textContent = `正在播报：${result.model}`;
      pauseBtn.disabled = false;
      resumeBtn.disabled = true;
      stopBtn.disabled = false;
    } catch (error) {
      status.textContent = error.message;
    } finally {
      playBtn.disabled = false;
    }
  });

  pauseBtn.addEventListener("click", () => {
    if (!currentSpeechAudio) return;
    currentSpeechAudio.pause();
    status.textContent = "已暂停";
    pauseBtn.disabled = true;
    resumeBtn.disabled = false;
  });

  resumeBtn.addEventListener("click", async () => {
    if (!currentSpeechAudio) return;
    await currentSpeechAudio.play();
    status.textContent = "正在播报";
    pauseBtn.disabled = false;
    resumeBtn.disabled = true;
  });

  stopBtn.addEventListener("click", () => stopSpeech(true));
}

function stopSpeech(updateStatus = true) {
  if (currentSpeechAudio) {
    currentSpeechAudio.pause();
    currentSpeechAudio.currentTime = 0;
    currentSpeechAudio = null;
  }
  if (!updateStatus) return;
  const status = document.getElementById("ttsStatus");
  const pauseBtn = document.getElementById("ttsPauseBtn");
  const resumeBtn = document.getElementById("ttsResumeBtn");
  const stopBtn = document.getElementById("ttsStopBtn");
  if (status) status.textContent = "已停止";
  if (pauseBtn) pauseBtn.disabled = true;
  if (resumeBtn) resumeBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = true;
}

function extractSpeechText(resource) {
  return stripMarkdownForSpeech(resource.content || "").slice(0, 6000);
}

function stripMarkdownForSpeech(text) {
  return String(text || "")
    .replace(/```[\s\S]*?```/g, " 代码示例。 ")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/<\/?[^>]+>/g, " ")
    .replace(/[#>*_`~\-]+/g, " ")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function renderQuizForm(quiz, level = 1) {
  return `
    <section class="quiz-panel" data-quiz-level="${escapeHtml(level)}">
      <div class="quiz-heading">
        <h2>在线答题</h2>
        <span>第 ${escapeHtml(level)} 套 · ${quiz.length} 题</span>
      </div>
      <div class="quiz-list">
        ${quiz.map(renderQuizItem).join("")}
      </div>
      <button id="submitQuizBtn" type="button" class="primary-btn quiz-submit">提交测验</button>
      <div id="quizResult" class="quiz-result hidden"></div>
    </section>
  `;
}

function renderQuizItem(item, index) {
  const name = `quiz_${escapeHtml(item.id)}`;
  const options = Array.isArray(item.options) ? item.options : [];
  const input =
    item.type === "single_choice" || item.type === "true_false"
      ? options
          .map(
            (option, optionIndex) => `
              <label class="quiz-option">
                <input type="radio" name="${name}" value="${String.fromCharCode(65 + optionIndex)}" />
                <span>${String.fromCharCode(65 + optionIndex)}. ${escapeHtml(cleanOptionText(option))}</span>
              </label>
            `,
          )
          .join("")
      : item.type === "multiple_choice"
        ? options
            .map(
              (option, optionIndex) => `
                <label class="quiz-option">
                  <input type="checkbox" name="${name}" value="${String.fromCharCode(65 + optionIndex)}" />
                  <span>${String.fromCharCode(65 + optionIndex)}. ${escapeHtml(cleanOptionText(option))}</span>
                </label>
              `,
            )
            .join("")
        : `<textarea class="quiz-text-answer" name="${name}" rows="3" placeholder="请输入你的答案"></textarea>`;

  return `
    <article class="quiz-item" data-question-id="${escapeHtml(item.id)}" data-type="${escapeHtml(item.type)}">
      <div class="quiz-meta">
        <span>${index + 1}. ${escapeHtml(item.type_label || "题目")}</span>
        <span>${escapeHtml(item.difficulty || "")}</span>
        <span>${escapeHtml(item.score || 0)} 分</span>
      </div>
      <p>${renderInline(item.question || "")}</p>
      <div class="quiz-inputs">${input}</div>
    </article>
  `;
}

function cleanOptionText(option) {
  return String(option || "")
    .replace(/^\s*[\(（]?[A-Ga-g][\)）]?\s*(?:[.．、:：]\s*)?/, "")
    .trim();
}

function bindQuizForm(resource) {
  const button = document.getElementById("submitQuizBtn");
  if (!button) return;
  button.addEventListener("click", async () => {
    if (!requireLogin()) return;
    button.disabled = true;
    button.textContent = "评分中";
    try {
      const result = await postJson("/api/quiz/submit", {
        course: document.getElementById("course").value.trim() || "机器学习",
        quiz: resource.quiz,
        answers: collectQuizAnswers(resource.quiz),
      });
      renderQuizResult(result, resource);
      dashboardLoaded = false;
    } catch (error) {
      document.getElementById("quizResult").classList.remove("hidden");
      document.getElementById("quizResult").innerHTML = `<strong>${escapeHtml(error.message)}</strong>`;
    } finally {
      button.disabled = false;
      button.textContent = "重新提交";
    }
  });
}

function collectQuizAnswers(quiz) {
  const answers = {};
  quiz.forEach((item) => {
    const selector = `[name="quiz_${CSS.escape(item.id)}"]`;
    if (item.type === "multiple_choice") {
      answers[item.id] = Array.from(document.querySelectorAll(`${selector}:checked`))
        .map((input) => input.value)
        .sort()
        .join("");
    } else if (item.type === "single_choice" || item.type === "true_false") {
      answers[item.id] = document.querySelector(`${selector}:checked`)?.value || "";
    } else {
      answers[item.id] = document.querySelector(selector)?.value || "";
    }
  });
  return answers;
}

function renderQuizResult(result, resource) {
  const container = document.getElementById("quizResult");
  if (!container) return;
  const passed = Number(result.percent || 0) >= 90;
  container.classList.remove("hidden");
  container.innerHTML = `
    <div class="quiz-settlement">
      <div>
        <span class="settlement-label">本次测试得分</span>
        <strong>${escapeHtml(result.percent)} 分</strong>
        <p>${escapeHtml(result.score)} / ${escapeHtml(result.total_score)}，答对 ${escapeHtml(result.correct_count)} / ${escapeHtml(result.total_count)}</p>
      </div>
      <div class="settlement-badge ${passed ? "pass" : "retry"}">${passed ? "达标" : "需巩固"}</div>
    </div>
    <p>${escapeHtml(result.summary || "")}</p>
    <div class="settlement-actions">
      <button id="toggleQuizReviewBtn" type="button" class="secondary-btn">查看答案与错题分析</button>
      ${
        passed
          ? '<button id="nextQuizBtn" type="button" class="primary-btn">做下一套测试题</button>'
          : '<button id="redoQuizBtn" type="button" class="primary-btn">重新作答</button>'
      }
    </div>
    <div id="quizReviewList" class="quiz-review-list hidden">
      <h3>答案与解析</h3>
      ${(result.details || [])
        .map(
          (item) => `
            <div class="quiz-review ${item.is_correct ? "correct" : "wrong"}">
              <strong>${escapeHtml(item.index)}. ${escapeHtml(item.is_correct ? "正确" : "需复盘")} · ${escapeHtml(item.knowledge_point || item.type_label)}</strong>
              <p>你的答案：${escapeHtml(item.student_answer || "未作答")}</p>
              <p>参考答案：${escapeHtml(item.correct_answer)}</p>
              <p>${escapeHtml(item.explanation || "")}</p>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
  document.getElementById("toggleQuizReviewBtn")?.addEventListener("click", () => {
    document.getElementById("quizReviewList")?.classList.toggle("hidden");
  });
  document.getElementById("redoQuizBtn")?.addEventListener("click", redoQuiz);
  document.getElementById("nextQuizBtn")?.addEventListener("click", () => loadNextQuiz(resource));
}

function redoQuiz() {
  document.querySelectorAll(".quiz-panel input").forEach((input) => {
    input.checked = false;
  });
  document.querySelectorAll(".quiz-panel textarea").forEach((textarea) => {
    textarea.value = "";
  });
  document.getElementById("quizResult")?.classList.add("hidden");
  document.querySelector(".quiz-panel")?.scrollIntoView({behavior: "smooth", block: "start"});
}

async function loadNextQuiz(resource) {
  const nextLevel = Number(resource.quiz_level || 1) + 1;
  const button = document.getElementById("nextQuizBtn");
  if (button) {
    button.disabled = true;
    button.textContent = "生成中";
  }
  try {
    const result = await postJson("/api/quiz/next", {
      course: document.getElementById("course").value.trim() || "机器学习",
      level: nextLevel,
    });
    resource.quiz = result.quiz || [];
    resource.quiz_level = result.level || nextLevel;
    const panel = document.querySelector(".quiz-panel");
    if (panel) {
      panel.outerHTML = renderQuizForm(resource.quiz, resource.quiz_level);
      bindQuizForm(resource);
      document.querySelector(".quiz-panel")?.scrollIntoView({behavior: "smooth", block: "start"});
    }
  } catch (error) {
    const resultBox = document.getElementById("quizResult");
    if (resultBox) {
      resultBox.classList.remove("hidden");
      resultBox.innerHTML = `<strong>${escapeHtml(error.message)}</strong>`;
    }
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
  if (!requireLogin()) return;
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
  if (!requireLogin()) return;
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
    headers: authHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function getJson(url) {
  const response = await fetch(url, {
    headers: authHeaders(false),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function login() {
  await authenticate("/api/auth/login", {
    username: authUsername.value.trim(),
    password: authPassword.value,
  });
}

async function register() {
  await authenticate("/api/auth/register", {
    username: authUsername.value.trim(),
    password: authPassword.value,
    student_id: authStudentId.value.trim() || authUsername.value.trim(),
  });
}

async function authenticate(url, payload) {
  try {
    const result = await postJson(url, payload);
    setAuth(result.access_token, result.user);
    setStatus("done", "已登录");
    dashboardLoaded = false;
    closeAuthModal();
    accountMenu.classList.add("hidden");
  } catch (error) {
    setStatus("error", "登录失败");
    authInfo.textContent = error.message;
  }
}

async function restoreSession() {
  if (!authToken) {
    updateAuthView();
    return;
  }
  try {
    currentUser = await getJson("/api/auth/me");
  } catch {
    authToken = "";
    currentUser = null;
    localStorage.removeItem("learning_auth_token");
  }
  updateAuthView();
}

function logout() {
  authToken = "";
  currentUser = null;
  localStorage.removeItem("learning_auth_token");
  dashboardLoaded = false;
  accountMenu.classList.add("hidden");
  updateAuthView();
  setStatus("", "待生成");
  setDashboardStatus("", "待刷新");
}

function setAuth(token, user) {
  authToken = token || "";
  currentUser = user || null;
  if (authToken) {
    localStorage.setItem("learning_auth_token", authToken);
  }
  updateAuthView();
}

function updateAuthView() {
  const loggedIn = Boolean(currentUser && authToken);
  if (loggedIn) {
    accountTrigger.textContent = currentUser.username;
    accountTrigger.classList.add("logged-in");
    accountName.textContent = currentUser.username;
    accountStudentId.textContent = `学生 ID：${currentUser.student_id}`;
    authInfo.textContent = `${currentUser.username} · ${currentUser.student_id}`;
    authStudentId.value = currentUser.student_id;
  } else {
    accountTrigger.textContent = "登录";
    accountTrigger.classList.remove("logged-in");
    accountName.textContent = "未登录";
    accountStudentId.textContent = "请先登录";
    authInfo.textContent = "登录后生成和查看你的个性化学习数据。";
    accountMenu.classList.add("hidden");
  }
  runBtn.disabled = !loggedIn;
  refreshDashboardBtn.disabled = !loggedIn;
  askBtn.disabled = !loggedIn;
}

function requireLogin() {
  if (authToken && currentUser) return true;
  setStatus("error", "请先登录");
  setDashboardStatus("error", "请先登录");
  openAuthModal();
  authInfo.textContent = "请先注册或登录学生账号。";
  return false;
}

function toggleAccount() {
  if (currentUser && authToken) {
    accountMenu.classList.toggle("hidden");
    return;
  }
  openAuthModal();
}

function openAuthModal() {
  authTitle.textContent = "登录";
  authModal.classList.remove("hidden");
  accountMenu.classList.add("hidden");
  authUsername.focus();
}

function closeAuthModal() {
  authModal.classList.add("hidden");
}

function authHeaders(withJson) {
  const headers = {};
  if (withJson) {
    headers["Content-Type"] = "application/json";
  }
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  return headers;
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
