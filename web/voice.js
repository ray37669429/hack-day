// 農民頁語音：朗讀＋收音＋關鍵詞比對。設計見 docs/voice-design.md。
// 朗讀先播 web/audio/ 的 Qwen3 TTS 音檔（文字必須和 audio/prompts.json 完全一樣），找不到才用瀏覽器語音。
// 不保存錄音，只回傳辨識出的文字。

export const LABEL = { yes: "是", no: "不是", unsure: "我不確定", self: "我自己", other: "別人",
  承租: "承租", 託耕: "託耕", 輪耕: "輪耕", 分耕: "分耕" };

const KW = {
  unsure: ["不知道", "不確定", "不清楚", "不曉得", "毋知", "無清楚", "袂記得"],
  no: ["不是", "不對", "沒有", "錯了", "毋是", "毋著", "毋對", "無"],
  // 不收「好、嗯、有」：太常出現在一般句子或語助詞，會被誤判成「是」
  yes: ["是", "對", "沒錯", "著", "係", "嘿"],
  other: ["別人", "人家", "別的人", "其他人", "予人", "佮人", "租給", "給人", "租人"],
  self: ["我自己", "自己", "家己", "我"],
  承租: ["承租", "租", "稅"], 託耕: ["託耕", "託", "代耕", "代種"], 輪耕: ["輪耕", "輪"], 分耕: ["分耕", "分"],
};
const hit = (k, t) => KW[k].some((w) => t.includes(w));

/** kind：yesno／who／cat。回傳答案代碼，聽不懂回傳 null。 */
export function match(kind, raw) {
  const t = String(raw).replace(/[\s，。！？、,.!?]/g, "");
  if (!t) return null;
  if (hit("unsure", t)) return "unsure";
  if (kind === "yesno") return hit("no", t) ? "no" : hit("yes", t) ? "yes" : null;
  if (kind === "who") return hit("other", t) ? "other" : hit("self", t) ? "self" : null;
  if (kind === "cat") {
    const found = ["承租", "託耕", "輪耕", "分耕"].filter((c) => hit(c, t));
    return found.length === 1 ? found[0] : null;
  }
  return null;
}

// ───── 朗讀
const audioMap = {};
const player = new Audio();
let voices = [];
if ("speechSynthesis" in window) {
  const load = () => (voices = speechSynthesis.getVoices());
  load();
  speechSynthesis.onvoiceschanged = load;
}

export async function loadAudio() {
  try {
    const r = await fetch("audio/manifest.json", { cache: "no-store" });
    if (!r.ok) return;
    const m = await r.json();
    for (const e of Object.values(m.items || {})) if (e.zh_text && e.files?.zh) audioMap[e.zh_text] = e.files.zh;
  } catch { /* 沒有音檔就用瀏覽器語音 */ }
}

export function stop() {
  try { player.pause(); } catch {}
  try { speechSynthesis?.cancel(); } catch {}
}

/** 唸一句話。回傳的 Promise 在唸完（或失敗）時結束，不會丟出錯誤。 */
export function speak(text) {
  stop();
  const file = audioMap[text];
  if (file) {
    return new Promise((done) => {
      player.src = `audio/${file}`;
      player.onended = done;
      player.onerror = () => browserSpeak(text).then(done);
      player.play().catch(() => browserSpeak(text).then(done));
    });
  }
  return browserSpeak(text);
}

function browserSpeak(text) {
  return new Promise((done) => {
    try {
      if (!("speechSynthesis" in window)) return done();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "zh-TW";
      u.rate = 0.85;
      const v = voices.find((x) => x.lang === "zh-TW") || voices.find((x) => /zh/i.test(x.lang));
      if (v) u.voice = v;
      u.onend = done;
      u.onerror = done;
      speechSynthesis.speak(u);
    } catch { done(); }
  });
}

// ───── 收音
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
export const canListen = Boolean(SR);
let recog = null;

/**
 * 聽一次。回傳 Promise：
 *   { alts: [...] }          聽到的候選文字（可能是空陣列＝沒聽到聲音）
 *   { error: "denied" }      麥克風被擋
 *   { error: "unsupported" } 瀏覽器不能收音
 */
export function listen() {
  stop();
  if (!SR) return Promise.resolve({ error: "unsupported" });
  return new Promise((done) => {
    let finished = false;
    const end = (r) => { if (!finished) { finished = true; recog = null; done(r); } };
    try {
      const r = new SR();
      recog = r;
      r.lang = "zh-TW";
      r.interimResults = false;
      r.maxAlternatives = 3;
      r.onresult = (e) => end({ alts: [...e.results[0]].map((a) => a.transcript) });
      r.onerror = (e) => end(e.error === "not-allowed" || e.error === "service-not-allowed" ? { error: "denied" } : { alts: [] });
      r.onend = () => end({ alts: [] });
      r.start();
    } catch { end({ error: "unsupported" }); }
  });
}

export function cancelListen() {
  try { recog?.abort(); } catch {}
}
