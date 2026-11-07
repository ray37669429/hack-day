// voice.js 的 speak() 一定會結束：音檔播不出來（play() 一直沒回應）要逾時結束；被下一句打斷要立刻結束。
// 由 tests/test_voice_js.py 用 node 執行。
import assert from "node:assert/strict";

globalThis.window = globalThis;
globalThis.Audio = class { play() { return new Promise(() => {}); } pause() {} };   // 永遠播不出來
globalThis.fetch = async () => ({ ok: true, json: async () => ({ items: { a: { zh_text: "測試", files: { zh: "zh/a.mp3" } } } }) });

const V = await import(new URL("../../web/voice.js", import.meta.url));
await V.loadAudio();

// 1. 被下一句打斷：上一句的 Promise 立刻結束
let t = Date.now();
const first = V.speak("測試");
V.speak("測試");
await first;
assert.ok(Date.now() - t < 200, "被打斷的那一句要立刻結束");

// 2. 播不出來：最晚約 5 秒（3 秒＋2 秒）結束
t = Date.now();
await V.speak("測試");
const ms = Date.now() - t;
assert.ok(ms >= 4500 && ms < 7000, `逾時結束的時間不對：${ms} ms`);
console.log("ok");
