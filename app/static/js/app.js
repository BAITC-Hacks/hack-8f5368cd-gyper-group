const IGNORED_TRANSCRIPTS = new Set([
  "you",
  "you.",
  "you!",
  "thank you",
  "thank you.",
  "subtitles",
  "subscribe",
  "bye",
  "a",
  "the",
]);

function isValidTranscript(text) {
  if (!text) return false;
  const clean = text.trim().toLowerCase();
  if (IGNORED_TRANSCRIPTS.has(clean)) return false;
  if (clean.length < 2) return false;
  return true;
}

function voiceLanguage() {
  return navigator.language?.toLowerCase().startsWith("kk") ? "kk" : "ru";
}

function voiceRouter() {
  return {
    socket: null,
    connected: false,
    listening: false,
    speaking: false,
    isProcessing: false,
    recognition: null,
    mediaRecorder: null,
    nativeRecognition: null,
    audioStream: null,
    audioChunks: [],
    audioSent: false,
    recordTimeout: null,
    audioContext: null,
    volumeFrame: null,
    recordingStartedAt: 0,
    lastVoiceAt: 0,
    heardVoice: false,
    noiseFloor: 0,
    speechStatus: "Голосовой ввод готов.",
    speechSupported: Boolean(
      (navigator.mediaDevices?.getUserMedia && window.MediaRecorder) ||
      window.SpeechRecognition ||
      window.webkitSpeechRecognition,
    ),
    draft: "",
    conversation: [],
    trace: { latency: {}, candidates: [], extracted_slots: {} },
    latencies: [
      { key: "stt_ms", label: "Speech-to-text", max: 500 },
      { key: "candidate_retrieval_ms", label: "Vector candidates", max: 100 },
      { key: "llm_routing_ms", label: "LLM decision", max: 700 },
      { key: "tts_ms", label: "Text-to-speech", max: 500 },
      { key: "total_ms", label: "End-to-end", max: 1500 },
    ],
    connect() {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      this.socket = new WebSocket(`${protocol}://${location.host}/ws/router`);
      this.socket.onopen = () => {
        this.connected = true;
      };
      this.socket.onclose = () => {
        this.connected = false;
        window.setTimeout(() => this.connect(), 1500);
      };
      this.socket.onmessage = (event) =>
        this.handleEvent(JSON.parse(event.data));
    },
    sendTranscript() {
      const transcript = this.draft.trim();
      if (!transcript || !this.connected) return;
      this.conversation.push({
        id: crypto.randomUUID(),
        role: "user",
        text: transcript,
      });
      this.socket.send(JSON.stringify({ type: "route", transcript }));
      this.draft = "";
      this.isProcessing = true;
    },
    handleEvent(event) {
      if (
        event.type === "trace" &&
        event.step === "transcript" &&
        isValidTranscript(event.transcript)
      ) {
        const lastMsg = this.conversation[this.conversation.length - 1];
        if (
          !lastMsg ||
          lastMsg.role !== "user" ||
          lastMsg.text !== event.transcript
        ) {
          this.conversation.push({
            id: crypto.randomUUID(),
            role: "user",
            text: event.transcript,
          });
        }
      }
      if (event.type === "routing") this.trace = { ...this.trace, ...event };
      if (event.type === "response") {
        if (isValidTranscript(event.transcript)) {
          const lastMsg = this.conversation[this.conversation.length - 1];
          if (
            !lastMsg ||
            lastMsg.role !== "user" ||
            lastMsg.text !== event.transcript
          ) {
            this.conversation.push({
              id: crypto.randomUUID(),
              role: "user",
              text: event.transcript,
            });
          }
        }
        this.trace = { ...event.decision, latency: event.latency };
        this.conversation.push({
          id: crypto.randomUUID(),
          role: "assistant",
          text: event.reply,
        });
        this.isProcessing = false;
        if (event.audio_base64)
          this.playAudio(event.audio_base64, event.audio_mime);
        else this.speak(event.reply, event.decision.language);
      }
      if (event.type === "error") {
        this.isProcessing = false;
        this.speechStatus = event.message;
        this.conversation.push({
          id: crypto.randomUUID(),
          role: "assistant",
          text: event.message,
        });
      }
    },
    toggleListening() {
      const Recognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Recognition || !this.connected) {
        this.speechStatus = "Распознавание речи недоступно в этом браузере.";
        return;
      }
      if (this.listening) {
        this.recognition.stop();
        return;
      }
      this.recognition = new Recognition();
      this.recognition.lang = voiceLanguage() === "kk" ? "kk-KZ" : "ru-RU";
      this.recognition.continuous = false;
      this.recognition.interimResults = false;
      this.recognition.maxAlternatives = 1;
      this.recognition.onstart = () => {
        this.listening = true;
        this.speechStatus = "Слушаю...";
      };
      this.recognition.onresult = (event) => {
        const transcript =
          event.results[event.resultIndex][0].transcript.trim();
        if (!transcript) return;
        this.conversation.push({
          id: crypto.randomUUID(),
          role: "user",
          text: transcript,
        });
        this.socket.send(JSON.stringify({ type: "route", transcript }));
        this.isProcessing = true;
        this.speechStatus = "Речь распознана, обрабатываю запрос...";
      };
      this.recognition.onerror = (event) => {
        this.listening = false;
        this.speechStatus =
          event.error === "not-allowed"
            ? "Разрешите доступ к микрофону в браузере."
            : "Не удалось распознать речь. Попробуйте ещё раз.";
      };
      this.recognition.onend = () => {
        this.listening = false;
        if (this.speechStatus === "Слушаю...")
          this.speechStatus = "Голосовой ввод готов.";
      };
      this.recognition.start();
    },
    async startListening() {
      const canRecordAudio = Boolean(
        navigator.mediaDevices?.getUserMedia && window.MediaRecorder,
      );
      if (canRecordAudio) {
        await this.startAudioRecording();
        return;
      }
      const Recognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;
      if (Recognition) {
        this.toggleListening();
        return;
      }
      this.speechStatus = "Голосовой ввод недоступен в этом браузере.";
    },
    async startAudioRecording() {
      if (this.listening) {
        this.stopListening();
        return;
      }
      if (!this.speechSupported || !this.connected) {
        this.speechStatus = "Микрофон или подключение к сервису недоступны.";
        return;
      }
      try {
        this.audioStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        this.audioChunks = [];
        this.audioSent = false;
        const mimeType = [
          "audio/webm;codecs=opus",
          "audio/webm",
          "audio/mp4",
        ].find((candidate) => MediaRecorder.isTypeSupported(candidate));
        this.mediaRecorder = new MediaRecorder(
          this.audioStream,
          mimeType ? { mimeType } : undefined,
        );
        this.mediaRecorder.ondataavailable = (event) => {
          if (event.data && event.data.size > 0) {
            this.audioChunks.push(event.data);
          }
        };
        this.mediaRecorder.onstop = async () => {
          this.listening = false;
          if (this.recordTimeout) clearTimeout(this.recordTimeout);
          this.recordTimeout = null;
          this.stopVolumeMonitor();
          if (this.audioStream) {
            this.audioStream.getTracks().forEach((track) => track.stop());
          }
          if (this.audioSent) return;
          const blob = new Blob(this.audioChunks, {
            type: this.mediaRecorder.mimeType || "audio/webm",
          });
          if (blob.size < 500) {
            this.speechStatus =
              "Запись слишком короткая или тихая. Попробуйте ещё раз.";
            return;
          }
          const payload = await this.toBase64(blob);
          this.audioSent = true;
          this.socket.send(
            JSON.stringify({
              type: "route_audio",
              audio_base64: payload,
              audio_mime: blob.type || "audio/webm",
              language_hint: voiceLanguage(),
            }),
          );
          this.isProcessing = true;
          this.speechStatus = "Распознаю аудио через OpenAI Whisper...";
        };
        this.mediaRecorder.start(250);
        this.listening = true;
        this.startVolumeMonitor();
        this.recordTimeout = window.setTimeout(() => {
          this.stopListening();
        }, 10000);
        this.speechStatus =
          "Идёт запись... Говорите. Нажмите повторно для отправки.";
      } catch (error) {
        this.listening = false;
        this.speechStatus =
          error.name === "NotAllowedError"
            ? "Разрешите доступ к микрофону в настройках браузера."
            : "Микрофон не найден или недоступен.";
      }
    },
    stopListening() {
      if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
        this.mediaRecorder.stop();
      }
      this.listening = false;
    },
    startNativeRecognition() {},
    startVolumeMonitor() {
      try {
        this.audioContext = new (
          window.AudioContext || window.webkitAudioContext
        )();
        this.audioContext.resume();
        const source = this.audioContext.createMediaStreamSource(
          this.audioStream,
        );
        const analyser = this.audioContext.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        const samples = new Uint8Array(analyser.fftSize);
        this.recordingStartedAt = performance.now();
        this.lastVoiceAt = this.recordingStartedAt;
        this.heardVoice = false;
        this.noiseFloor = 0;
        let calibrationFrames = 0;
        const detect = () => {
          if (!this.listening) return;
          analyser.getByteTimeDomainData(samples);
          const energy =
            samples.reduce((total, value) => total + (value - 128) ** 2, 0) /
            samples.length;
          const volume = Math.sqrt(energy) / 128;
          const now = performance.now();
          if (calibrationFrames < 20 && !this.heardVoice) {
            this.noiseFloor += volume;
            calibrationFrames += 1;
          }
          const threshold = Math.max(
            (this.noiseFloor / Math.max(calibrationFrames, 1)) * 1.35,
            0.003,
          );
          if (volume > threshold) {
            this.heardVoice = true;
            this.lastVoiceAt = now;
          }
          if (
            (this.heardVoice && now - this.lastVoiceAt > 1500) ||
            now - this.recordingStartedAt > 10000
          ) {
            this.stopListening();
            return;
          }
          this.volumeFrame = requestAnimationFrame(detect);
        };
        this.volumeFrame = requestAnimationFrame(detect);
      } catch (e) {
        console.warn("Volume monitor init failed:", e);
      }
    },
    stopVolumeMonitor() {
      if (this.volumeFrame) cancelAnimationFrame(this.volumeFrame);
      this.volumeFrame = null;
      if (this.audioContext) this.audioContext.close();
      this.audioContext = null;
    },
    toBase64(blob) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result.split(",")[1]);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    },
    playAudio(encodedAudio, mimeType) {
      const bytes = Uint8Array.from(atob(encodedAudio), (character) =>
        character.charCodeAt(0),
      );
      const url = URL.createObjectURL(
        new Blob([bytes], { type: mimeType || "audio/mpeg" }),
      );
      const audio = new Audio(url);
      audio.onplay = () => {
        this.speaking = true;
        this.speechStatus = "Озвучиваю ответ...";
      };
      audio.onended = () => {
        this.speaking = false;
        this.speechStatus = "Голосовой ввод готов.";
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        this.speaking = false;
        URL.revokeObjectURL(url);
        this.speak("Не удалось воспроизвести аудио.", "ru");
      };
      audio
        .play()
        .catch(() => this.speak("Не удалось воспроизвести аудио.", "ru"));
    },
    speak(text, language) {
      if (!("speechSynthesis" in window)) return;
      speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = language === "kk" ? "kk-KZ" : "ru-RU";
      utterance.onstart = () => {
        this.speaking = true;
        this.speechStatus = "Озвучиваю ответ...";
      };
      utterance.onend = () => {
        this.speaking = false;
        this.speechStatus = "Голосовой ввод готов.";
      };
      utterance.onerror = () => {
        this.speaking = false;
        this.speechStatus = "Не удалось озвучить ответ.";
      };
      speechSynthesis.speak(utterance);
    },
    stopSpeaking() {
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      this.speaking = false;
      this.speechStatus = "Озвучивание остановлено.";
    },
    clearConversation() {
      this.conversation = [];
      this.stopSpeaking();
      this.trace = { latency: {}, candidates: [], extracted_slots: {} };
    },
  };
}
