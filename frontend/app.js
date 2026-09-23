const WS_URL = "ws://localhost:8000/ws/voice";
const UI = {
  ru: { client:"Клиент", supervisor:"Супервизор", voiceAssistant:"Голосовой помощник", ready:"Нажмите, чтобы говорить", listening:"Слушаю…", thinking:"Думаю…", answering:"Отвечаю…", voiceHint:"Расскажите, чем мы можем помочь", dialogue:"Диалог", newChat:"+ Новый чат", connecting:"Подключение…", connected:"На связи", disconnected:"Нет соединения", emptyChat:"Ваш разговор появится здесь", textPlaceholder:"Напишите сообщение", send:"Отправить", liveTrace:"Live trace", supervisorTitle:"Трассировка диалога", currentTranscript:"Текущая реплика", selectedScenario:"Выбранный сценарий", alternatives:"Альтернативы", slots:"Параметры", latency:"Задержка по этапам", noTrace:"Нет данных для отображения", handoff:"Передача оператору", normal:"в пределах нормы", slow:"требует внимания", clientLabel:"Клиент", robotLabel:"Saqta Insurance" },
  kk: { client:"Клиент", supervisor:"Супервайзер", voiceAssistant:"Дауыстық көмекші", ready:"Сөйлеу үшін басыңыз", listening:"Тыңдап тұрмын…", thinking:"Ойланып жатырмын…", answering:"Жауап беріп жатырмын…", voiceHint:"Қалай көмектесе алатынымызды айтыңыз", dialogue:"Диалог", newChat:"+ Жаңа чат", connecting:"Қосылуда…", connected:"Байланыстамыз", disconnected:"Байланыс жоқ", emptyChat:"Сөйлесуіңіз осында шығады", textPlaceholder:"Хабарлама жазыңыз", send:"Жіберу", liveTrace:"Live trace", supervisorTitle:"Диалог трассировкасы", currentTranscript:"Ағымдағы реплика", selectedScenario:"Таңдалған сценарий", alternatives:"Баламалы нұсқалар", slots:"Параметрлер", latency:"Кезеңдер бойынша кідіріс", noTrace:"Көрсетуге дерек жоқ", handoff:"Операторға беру", normal:"норма шегінде", slow:"назар аударуды қажет етеді", clientLabel:"Клиент", robotLabel:"Saqta Insurance" }
};
let uiLanguage = localStorage.getItem("halyk-ui-language") || "ru";
let socket, recorder, recognition, audioChunks = [], latestTrace = null, currentChat = [], currentSessionId = null;
const $ = (selector) => document.querySelector(selector);

function applyLanguage(language) {
  uiLanguage = language;
  localStorage.setItem("halyk-ui-language", language);
  document.documentElement.lang = language === "kk" ? "kk" : "ru";
  document.querySelectorAll("[data-i18n]").forEach((element) => { element.textContent = UI[language][element.dataset.i18n]; });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => { element.placeholder = UI[language][element.dataset.i18nPlaceholder]; });
  document.querySelectorAll("[data-ui-lang]").forEach((button) => button.classList.toggle("active", button.dataset.uiLang === language));
  if (latestTrace) renderTrace(latestTrace);
}

function connect() {
  socket = new WebSocket(WS_URL);
  updateConnection("connecting");
  socket.onopen = () => updateConnection("connected");
  socket.onclose = () => { updateConnection("disconnected"); setTimeout(connect, 2500); };
  socket.onerror = () => socket.close();
  socket.onmessage = ({ data }) => {
    try { handleBackendMessage(JSON.parse(data)); } catch { /* Ignore non-JSON streaming frames. */ }
  };
}

function updateConnection(state) {
  const label = $("#connectionStatus");
  label.classList.toggle("connected", state === "connected");
  label.innerHTML = `● <span>${UI[uiLanguage][state]}</span>`;
}

function send(payload) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
  else updateConnection("disconnected");
}

function addMessage(role, text, language, track = true) {
  $("#emptyState")?.remove();
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const label = role === "client" ? UI[uiLanguage].clientLabel : UI[uiLanguage].robotLabel;
  item.innerHTML = `<div class="message-meta"><span>${label}</span>${language ? `<span class="language-badge">${language.toUpperCase()}</span>` : ""}</div><div></div>`;
  item.lastElementChild.textContent = text;
  $("#messages").append(item);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  if (track) currentChat.push({ role, text, language: language || "" });
}

function saveCurrentChat() {
  if (!currentChat.some((message) => message.role === "client")) return;
  const savedSessions = JSON.parse(localStorage.getItem("saqta-chat-sessions") || "[]");
  const sessions = savedSessions.filter((session, index) => savedSessions.findIndex((item) => item.title === session.title) === index);
  const clientMessage = currentChat.find((message) => message.role === "client");
  const session = { id: currentSessionId || Date.now(), title: clientMessage.text, messages: currentChat, savedAt: new Date().toISOString() };
  currentSessionId = session.id;
  const next = [session, ...sessions.filter((item) => item.id !== session.id)].slice(0, 12);
  localStorage.setItem("saqta-chat-sessions", JSON.stringify(next));
}

function startNewChat() {
  saveCurrentChat();
  currentChat = [];
  currentSessionId = null;
  $("#messages").innerHTML = `<div class="empty-state" id="emptyState">${UI[uiLanguage].emptyChat}</div>`;
  renderHistory();
}

function renderHistory() {
  const list = $("#historyList");
  const allSessions = JSON.parse(localStorage.getItem("saqta-chat-sessions") || "[]");
  const sessions = allSessions.filter((session, index) => allSessions.findIndex((item) => item.title === session.title) === index);
  const markup = sessions.length ? sessions.map((item) => `<button type="button" data-chat-id="${item.id}" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</button>`).join("") : "<span class=\"history-empty\">История чатов появится здесь</span>";
  list.innerHTML = markup;
  $("#mobileHistoryList").innerHTML = markup;
  document.querySelectorAll("#historyList button, #mobileHistoryList button").forEach((button) => button.addEventListener("click", () => openSavedChat(Number(button.dataset.chatId))));
}

function openSavedChat(id) {
  const sessions = JSON.parse(localStorage.getItem("saqta-chat-sessions") || "[]");
  const session = sessions.find((item) => item.id === id);
  if (!session) return;
  currentChat = session.messages || [];
  currentSessionId = session.id;
  $("#messages").innerHTML = "";
  currentChat.forEach((message) => addMessage(message.role, message.text, message.language, false));
  $("#appShell").classList.remove("mobile-history-active");
}

function handleBackendMessage(message) {
  const trace = message.trace || message;
  const transcript = message.transcript || trace.transcript;
  if (transcript) addMessage("client", transcript, trace.language);
  if (message.response_text) { addMessage("bot", message.response_text, trace.language); setStatus("answering"); }
  if (message.audio_base64) playAudio(message.audio_base64);
  else if (message.response_text) speakResponse(message.response_text, trace.language);
  if (trace?.turn !== undefined) { latestTrace = trace; renderTrace(trace); }
  if (message.handoff || message.need_handoff) renderHandoff(message);
  setTimeout(() => setStatus("ready"), 500);
}

function playAudio(encoded) {
  const audio = new Audio(encoded.startsWith("data:") ? encoded : `data:audio/mpeg;base64,${encoded}`);
  audio.play().catch(() => {});
}

function speakResponse(text, language) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = language === "kk" ? "kk-KZ" : "ru-RU";
  window.speechSynthesis.speak(utterance);
}

function setStatus(key) { $("#voiceStatus").textContent = UI[uiLanguage][key]; }

function confidenceRow(item, alternative = false) {
  const confidence = Math.max(0, Math.min(1, Number(item.confidence) || 0));
  return `<div class="${alternative ? "alternative" : ""}"><div class="scenario-title"><b>${escapeHtml(item.scenario_id || "—")}</b><span>${Math.round(confidence * 100)}%</span></div><div class="confidence-track"><div class="confidence-fill" style="width:${confidence * 100}%"></div></div></div>`;
}

function renderTrace(trace) {
  $("#traceTurn").textContent = trace.turn ? `Turn ${trace.turn}` : "—";
  $("#traceTranscript").textContent = trace.transcript || UI[uiLanguage].noTrace;
  const selected = trace.scenarios?.[0];
  $("#selectedScenario").innerHTML = selected ? `${confidenceRow(selected)}<p class="reason">${escapeHtml(trace.reason || "—")}</p>` : UI[uiLanguage].noTrace;
  $("#alternatives").innerHTML = trace.alternatives?.length ? trace.alternatives.map((item) => confidenceRow(item, true)).join("") : UI[uiLanguage].noTrace;
  const slots = Object.entries(trace.slots || {});
  $("#slots").innerHTML = slots.length ? slots.map(([key, value]) => `<div class="kv-row"><span>${escapeHtml(key)}</span><b>${escapeHtml(String(value))}</b></div>`).join("") : UI[uiLanguage].noTrace;
  renderLatency(trace.latency_ms || {});
}

function renderLatency(latency) {
  const stages = ["stt", "triage", "router", "response", "tts_first_audio"];
  const total = Number(latency.total) || stages.reduce((sum, stage) => sum + (Number(latency[stage]) || 0), 0);
  const max = Math.max(...stages.map((stage) => Number(latency[stage]) || 0), 1);
  $("#latencyBars").innerHTML = stages.map((stage) => { const value = Number(latency[stage]) || 0; return `<div class="latency-row"><span>${stage}</span><i><b style="width:${(value / max) * 100}%"></b></i><b>${Math.round(value)} ms</b></div>`; }).join("");
  const badge = $("#latencyBadge");
  badge.textContent = `${Math.round(total)} ms · ${total <= 1500 ? UI[uiLanguage].normal : UI[uiLanguage].slow}`;
  badge.classList.toggle("slow", total > 1500);
}

function renderHandoff(message) {
  const card = $("#handoffCard");
  card.classList.remove("hidden");
  $("#handoffText").textContent = message.reason || message.handoff?.reason || "—";
  const summary = message.context_summary || message.handoff?.context_summary;
  $("#handoffSummary").textContent = summary ? (typeof summary === "string" ? summary : JSON.stringify(summary)) : "";
}

async function toggleRecording(openVoice = true, sourceButton = $("#micButton")) {
  const button = sourceButton;
  if (openVoice) openAssistant();
  if (recorder?.state === "recording") { recorder.stop(); button.classList.remove("recording"); setStatus("thinking"); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream);
    audioChunks = [];
    recorder.ondataavailable = (event) => audioChunks.push(event.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      const buffer = await new Blob(audioChunks, { type: recorder.mimeType }).arrayBuffer();
      send({ type: "audio", mime_type: recorder.mimeType, audio_base64: arrayBufferToBase64(buffer) });
    };
    recorder.start(); button.classList.add("recording"); setStatus("listening");
  } catch { setStatus("ready"); }
}

function openAssistant() { $("#appShell").classList.add("voice-mode"); }
function closeAssistant() { if (recognition) recognition.stop(); if (recorder?.state === "recording") recorder.stop(); $("#appShell").classList.remove("voice-mode"); setStatus("ready"); }

function arrayBufferToBase64(buffer) { let binary = ""; new Uint8Array(buffer).forEach((byte) => binary += String.fromCharCode(byte)); return btoa(binary); }
function escapeHtml(value) { const node = document.createElement("div"); node.textContent = value; return node.innerHTML; }

$("#textForm").addEventListener("submit", (event) => { event.preventDefault(); const input = $("#textInput"); const text = input.value.trim(); if (!text) return; send({ type: "text", text }); addMessage("client", text); input.value = ""; setStatus("thinking"); });
$("#micButton").addEventListener("click", toggleRecording);
$("#chatMicButton").addEventListener("click", () => toggleRecording(false, $("#chatMicButton")));
$("#assistantButton").addEventListener("click", () => toggleRecording(true));
$("#exitVoiceButton").addEventListener("click", closeAssistant);
$("#newChatButton").addEventListener("click", startNewChat);
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { $("#textInput").value = button.dataset.prompt; $("#textInput").focus(); }));
document.querySelectorAll("[data-mobile-view]").forEach((button) => button.addEventListener("click", () => {
  const view = button.dataset.mobileView;
  document.querySelectorAll("[data-mobile-view]").forEach((item) => item.classList.toggle("active", item === button));
  if (view === "voice") { toggleRecording(true); return; }
  $("#appShell").classList.toggle("mobile-history-active", view === "history");
}));
$("#backToChat").addEventListener("click", () => { $("#appShell").classList.remove("mobile-history-active"); document.querySelector('[data-mobile-view="chat"]').click(); });
function closeDrawer() { $("#mobileDrawer").classList.remove("open"); $("#mobileDrawer").setAttribute("aria-hidden", "true"); }
$("#menuButton").addEventListener("click", () => { $("#mobileDrawer").classList.add("open"); $("#mobileDrawer").setAttribute("aria-hidden", "false"); });
$("#drawerClose").addEventListener("click", closeDrawer);
document.querySelectorAll("[data-drawer-view]").forEach((button) => button.addEventListener("click", () => {
  const view = button.dataset.drawerView; const shell = $("#appShell");
  shell.classList.remove("mobile-history-active", "supervisor-mobile");
  if (view === "history") shell.classList.add("mobile-history-active");
  if (view === "supervisor") shell.classList.add("supervisor-mobile");
  closeDrawer();
}));
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => { document.querySelectorAll("[data-view]").forEach((item) => item.classList.toggle("active", item === button)); document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `${button.dataset.view}-view`)); }));
document.querySelectorAll("[data-ui-lang]").forEach((button) => button.addEventListener("click", () => applyLanguage(button.dataset.uiLang)));
applyLanguage(uiLanguage);
renderHistory();
connect();
window.addEventListener("beforeunload", saveCurrentChat);
