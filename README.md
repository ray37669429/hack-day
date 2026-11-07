# 農業產銷履歷 AI 黑客松：謄本 → Excel → Word

把一組土地的謄本，經 AI 擷取和人工確認，變成土地清單 Excel，再自動帶入「土地使用同意書」Word。

今天只做 1 組案例：謄本 2 頁 → 清單 3–5 筆 → 同意書 1 份。
完整背景、欄位對照、驗收方法見張永錫撰寫的白皮書 [docs/whitepaper.md](docs/whitepaper.md)。

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
3. 類別、耕作人、實施期間由人輸入，AI 不填。
4. 所有權人與耕作人分欄，不自動合併。
5. 未確認的 Word 一律標「草稿」。
6. 不自動送出正式系統。

## 協作方式

```bash
git clone https://github.com/ray37669429/hack-day.git
```

1. `main` 永遠可以跑、可以 demo。
2. 每人一條分支：`feat/<名字>-<功能>`，例如 `feat/ray-excel-to-word`。
3. 小步 commit、常 push；合回 `main` 走 Pull Request。
4. 金鑰只放 `.env`（照 `.env.example`），不要 commit。

## AI 工具（Codex / Claude Code 都可以）

| 檔案 | 誰讀 | 用途 |
| --- | --- | --- |
| [AGENTS.md](AGENTS.md) | Codex 直接讀；Claude Code 透過 CLAUDE.md 讀 | **唯一的規則來源**，要改規則改這裡 |
| [CLAUDE.md](CLAUDE.md) | Claude Code | 只有一行 `@AGENTS.md` 引用，不另寫規則 |

個人偏好（不想給隊友的設定）放 `CLAUDE.local.md` 或 `AGENTS.override.md`，這兩個不會進 git。

## 待辦 / 驗收

- 流程圖：[線上版](https://claude.ai/artifact/BJBLf1Ptn71F6ZGS3aysuA)（需分享權限）／原始檔 [docs/flow.html](docs/flow.html)
- 系統設計討論稿（參考 Palantir Ontology）：[docs/ontology-design.md](docs/ontology-design.md)
- 待辦與時間表：[docs/TODO.md](docs/TODO.md)
- 驗收記錄：[docs/acceptance-log.md](docs/acceptance-log.md)
