# 怎麼參與修改

歡迎任何人改這個專案。所有修改都透過 **Pull Request（PR）** 送進來，維護者看過、自動測試通過後合併。

## 最簡單的方式：直接在 GitHub 網頁上改

1. 打開要改的檔案，點右上角的 ✏️（Edit this file）。
2. 改完後在下方寫一句說明，選「Propose changes」。
3. GitHub 會自動幫你複製一份並開好 PR，按「Create pull request」就完成了。

適合改文件、提示詞、題目文字等小修改。

## 在自己電腦上改（程式修改）

```bash
# 先在 GitHub 上按右上角 Fork，再複製你自己的那份
git clone https://github.com/<你的帳號>/hack-day.git
cd hack-day
py -3.10 -m venv .venv                # macOS / Linux：python3.10 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q     # 送 PR 前請確認全部通過
git checkout -b fix/簡短說明
# 修改、commit、push 到你的 fork，再到 GitHub 開 PR
```

不需要任何 API 金鑰就能跑測試（AI 擷取用錄好的回應離線測試）。

## 必須遵守

- **不能放真實個資**：姓名、身分證號、地址、真實地號、謄本照片都不可以出現在程式碼、測試、文件或 commit 訊息。測試請用 `data/samples/fake-transcripts/` 的虛構資料。
- **不能放金鑰**：金鑰只放自己的 `.env`（已被 git 排除）。
- **遵守 [AGENTS.md](AGENTS.md)** 的規則，尤其是「不猜」：看不清的欄位一律「待確認」，AI 不能確認任何欄位。
- 改到擷取提示詞（`app/llm/tasks/`）時要升 `PROMPT_VERSION`，並說明評分結果。
- 一個 PR 只做一件事，說明寫清楚改了什麼、為什麼。

## 回報問題

到 [Issues](../../issues) 開一則，寫下發生什麼事、預期是什麼、怎麼重現。不要附上真實謄本或個資。
