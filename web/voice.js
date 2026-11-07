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
  // 「有沒有」類的題目（例如有沒有租約）：先找否定，再找「有」
  haveNo: ["沒有", "沒", "無", "毋"],
  have: ["有"],
  // 核對題「謄本上寫的跟你知道的一樣嗎」：先找「不一樣」類（含「一樣」兩個字），再找「一樣」類
  diff: ["不一樣", "不同", "不對", "錯", "不是", "毋是", "毋著", "無仝", "無共款"],
  same: ["一樣", "相同", "對", "是", "仝款", "共款", "著"],
};
const hit = (k, t) => KW[k].some((w) => t.includes(w));
const clean = (raw) => String(raw ?? "").replace(/[\s，。！？、,.!?]/g, "");

// 「三年」「3年」「五」→ 數字。句子裡的每個數字都抓出來（十五、115 也照樣算成一個數）。
const CN = { 一: 1, 壹: 1, 二: 2, 兩: 2, 三: 3, 參: 3, 四: 4, 五: 5, 伍: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
function cnNum(w) {
  if (!w.includes("十")) return [...w].reduce((n, c) => n * 10 + (CN[c] ?? 0), 0);
  const [a, b] = w.split("十");
  return (a ? CN[a] ?? 1 : 1) * 10 + (b ? CN[b] ?? 0 : 0);
}
const numbersIn = (t) => (t.match(/\d+|[一壹二兩三參四五伍六七八九十]+/g) || []).map((w) => (/^\d+$/.test(w) ? Number(w) : cnNum(w)));
/** 句子裡提到的年數，只算 allowed 裡的；剛好一個才回傳，沒有或好幾個（模稜兩可）回傳 null。 */
function yearsIn(t, allowed) {
  const found = [...new Set(numbersIn(t.replace(/一下|一樣|一點|一定/g, "")).filter((n) => allowed.includes(n)))];
  return found.length === 1 ? String(found[0]) : null;
}

/** 選項文字是不是否定的說法（不是、沒有、不知道…），用來對應 yes／no。 */
export const isNegative = (label) => /^(不|沒|無|毋)/.test(clean(label));

/** kind：yesno／who／cat／have／same／years。回傳答案代碼，聽不懂回傳 null。 */
export function match(kind, raw) {
  const t = clean(raw);
  if (!t) return null;
  if (hit("unsure", t)) return "unsure";
  if (kind === "yesno") return hit("no", t) ? "no" : hit("yes", t) ? "yes" : null;
  if (kind === "have") return hit("haveNo", t) ? "no" : hit("have", t) ? "yes" : null;
  if (kind === "who") return hit("other", t) ? "other" : hit("self", t) ? "self" : null;
  if (kind === "same") {
    const u = t.replace(/沒錯|不錯/g, "對"); // 「沒錯」「不錯」是對，不要被「錯」吃掉
    return hit("diff", u) ? "no" : hit("same", u) ? "yes" : null;
  }
  if (kind === "years") return yearsIn(t, [1, 3, 5]);
  if (kind === "cat") {
    const found = ["承租", "託耕", "輪耕", "分耕"].filter((c) => hit(c, t));
    return found.length === 1 ? found[0] : null;
  }
  return null;
}

/**
 * 依題目的選項比對，回傳選項的 value，聽不懂回傳 null。
 * q = { kind, options: [{ value, label }] }（options 含 unsure）。
 * 順序：整句剛好等於某個選項文字 → 依 kind 的關鍵詞 → 句子裡只出現一個選項文字。
 */
export function matchOption(q, raw) {
  const t = clean(raw);
  if (!t) return null;
  const opts = q.options || [];
  const exact = opts.find((o) => clean(o.label) === t);
  if (exact) return exact.value;
  if (q.kind === "years") {
    // 年數照這題的選項比對（選項 value 是 "1"／"3"／"5"）
    if (hit("unsure", t)) return "unsure";
    const allowed = opts.map((o) => Number(o.value)).filter((n) => Number.isInteger(n) && n > 0);
    const y = yearsIn(t, allowed.length ? allowed : [1, 3, 5]);
    return y && opts.some((o) => o.value === y) ? y : null;
  }
  const code = match(q.kind, raw);
  if (code) {
    const byValue = opts.find((o) => o.value === code);
    if (byValue) return byValue.value;
    if (code === "unsure") return "unsure";
    if (code === "yes" || code === "no") {
      const main = opts.filter((o) => o.value !== "unsure");
      const o = main.find((x) => isNegative(x.label) === (code === "no"));
      if (o) return o.value;
    }
  }
  if (hit("unsure", t)) return "unsure";
  const found = opts.filter((o) => o.value !== "unsure" && o.label && t.includes(clean(o.label)));
  return found.length === 1 ? found[0].value : null;
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
