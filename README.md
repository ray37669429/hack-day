# 農業產銷履歷 AI 黑客松：謄本 → Excel → Word

把一組土地的謄本，經 AI 擷取和人工確認，變成土地清單 Excel，再自動帶入「土地使用同意書」Word。

今天只做 1 組案例：謄本 2 頁 → 清單 3–5 筆 → 同意書 1 份。
完整背景、欄位對照、驗收方法見張永錫撰寫的白皮書 [docs/whitepaper.md](docs/whitepaper.md)。

## 快速展示（約 5 分鐘，不需要任何金鑰）

```bash
git clone https://github.com/ray37669429/hack-day.git
cd hack-day
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8001
```

打開 <http://localhost:8001/>（Agent 工作台），按上方藍色的 **「▶ 自動展示」**：
系統用虛構的假謄本（C02：一筆地兩位地主共有）自己跑完整個流程，約 2 分鐘、14 步，邊跑邊解說。

- **左**：高齡農民的手機頁（大字、大按鈕、可聽可講）：拍照被退件 → 重拍 → 核對謄本 → 回答 → 法律注意事項 → 下載同意書。
- **中**：每個背景 agent 的即時狀態流程圖，以及擷取出來的土地、地主、欄位主張。
- **右**：agent 事件串流——每個 agent 做了什麼。

展示用假謄本與事先產生的語音檔，**不需要 `.env` 或 API 金鑰**。要讓 AI 讀真的謄本照片，才需要在 `.env` 填 `OPENAI_API_KEY`（照 `.env.example`，不要 commit）。
農民手機頁可以單獨打開：工作台上方的「另開農民頁」。

## 系統一句話

農民只做：拍照、用「一樣／不一樣」核對 AI 讀出的資料、回答幾個是非題、選要簽幾年、下載同意書簽名。
AI 只能建立「待確認」的擷取結果，**只有農民本人能確認**；有看不清或不確定的地方，同意書就是「草稿」並列出待辦。

## 團隊

| 角色 | 負責 |
| --- | --- |
| 隊員 A（地政背景） | 謄本欄位辨識、地號與面積核對 |
| 隊員 B（電腦老師） | 工具與流程、確保現場可重跑 |
| 隊員 C（張永錫，白皮書作者） | 需求、計時、範圍決策、驗收 |
| 實際使用者（永錫的太太） | 確認成果、試用 |

## 資料夾

| 位置 | 放什麼 | 進 git？ |
| --- | --- | --- |
| `templates/` | 空白 Excel 清單、空白 Word 同意書 | 是 |
| `data/samples/` | **已遮蔽**的樣本與正確答案 | 是 |
| `data/raw/` | 原始未遮蔽謄本、真實檔案 | **否** |
| `data/output/` | 程式產出的 Excel / Word | **否** |
| `docs/` | 白皮書、待辦、驗收記錄 | 是 |

## 硬規則（違反即退回）

1. **不猜**：看不清、缺頁、衝突一律標「待確認」，不靜默補值。
2. **個資不進 git**：姓名、身分證、電話、簽名用代碼（農民 A、土地 A）。原始檔只放 `data/raw/`。
3. 類別、實施期間由農民回答與選擇，AI 不填；耕作人姓名及 ID 留白，簽署時手寫。
4. 所有權人與耕作人分欄，不自動合併。
5. 未確認的 Word 一律標「草稿」。
6. 不自動送出正式系統。

## 參與修改

歡迎任何人改：在 GitHub 網頁點檔案右上角的 ✏️ 就能編輯並送出 Pull Request，詳見 [CONTRIBUTING.md](CONTRIBUTING.md)。每個 PR 會自動跑測試。

## 開發方式（單人）

```bash
git clone https://github.com/ray37669429/hack-day.git
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8001
```

1. `main` 永遠可以跑、可以 demo；在 `main` 上小步 commit，commit 前先跑測試。
2. 可以同時開 Claude Code 和 Codex，但兩個 AI 不要改同一個檔案。
3. 金鑰只放 `.env`（照 `.env.example`），不要 commit。

## AI 工具（Codex / Claude Code 都可以）

| 檔案 | 誰讀 | 用途 |
| --- | --- | --- |
| [AGENTS.md](AGENTS.md) | Codex 直接讀；Claude Code 透過 CLAUDE.md 讀 | **唯一的規則來源**，要改規則改這裡 |
| [CLAUDE.md](CLAUDE.md) | Claude Code | 只有一行 `@AGENTS.md` 引用，不另寫規則 |

個人偏好（不想給隊友的設定）放 `CLAUDE.local.md` 或 `AGENTS.override.md`，這兩個不會進 git。

## 待辦 / 驗收

- 流程圖：[線上版](https://claude.ai/artifact/BJBLf1Ptn71F6ZGS3aysuA)（需分享權限）／原始檔 [docs/flow.html](docs/flow.html)
- **Agent 工作台與自動展示**：[web/dev.html](web/dev.html)；**農民手機頁**：[web/farmer.html](web/farmer.html)（說明見 [web/README.md](web/README.md)）
- 前端設計：[docs/frontend-design.md](docs/frontend-design.md)；法律注意事項規則：[docs/legal-questions.md](docs/legal-questions.md)
- 舊的離線測試台（含已取消的協助者分頁）：[web/prototype.html](web/prototype.html)
- **3 小時開發計畫（單人）**：[docs/3h-mvp-plan.md](docs/3h-mvp-plan.md)
- **後端設計**：[docs/backend-design.md](docs/backend-design.md)
- **LLM harness（OpenAI）**：[docs/llm-harness.md](docs/llm-harness.md)
- 語音設計（國語朗讀用 OpenAI TTS 事先產生）：[docs/voice-design.md](docs/voice-design.md)
- 同意書版面與欄位規格：[docs/agreement-spec.md](docs/agreement-spec.md)（產生器：`python tools/make_agreement.py`）
- 系統設計討論稿（參考 Palantir Ontology）：[docs/ontology-design.md](docs/ontology-design.md)
- 高齡農民介面與背景 agent 討論稿：[docs/farmer-ux-agents.md](docs/farmer-ux-agents.md)
- 待辦與時間表：[docs/TODO.md](docs/TODO.md)
- 驗收記錄：[docs/acceptance-log.md](docs/acceptance-log.md)
