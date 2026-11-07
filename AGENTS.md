# AGENTS.md — AI 協作規則（Codex 與 Claude Code 共用）

這份是唯一的規則來源。Codex 直接讀這個檔；Claude Code 透過 `CLAUDE.md` 引用它。
要改規則就改這裡，不要在 `CLAUDE.md` 另寫一份。

## 專案

黑客松專案：謄本 → 土地清單 Excel → 土地使用同意書 Word。
完整需求、欄位對照、驗收方法見 `docs/whitepaper.md`；待辦見 `docs/TODO.md`。
系統設計（Ontology：物件、Action、送出條件）見 `docs/ontology-design.md`，目前是討論稿；寫資料模型或改資料的程式前先讀它。
核心原則：Excel 與 Word 只是輸出視圖；所有資料修改都要經過 Action，AI 只能建立「待確認」的擷取主張。
**沒有協助者**（2026-11-07 使用者決定取消）：農民本人在手機上核對 AI 讀出的資料、選實施期間，最後自己下載同意書。

## 硬規則（違反即退回）

- 不捏造、不猜：看不清、缺漏、衝突的欄位標「待確認」，絕不補值。
- 不用 AI 自報的信心分數取代人工核對。只有農民本人（actor `farmer`）能把欄位標成已確認；看不清的欄位不能靠「一樣」確認。
- 類別（農民第 3 題）、實施期間（農民選 1／3／5 年）由農民決定，不要讓 AI 填；乙方耕作人姓名及 ID 留白，簽署時手寫。
- 備註只放規則產生的**固定範本**提醒（例如「共有土地：需其他共有人同意」），不放 AI 自由產生的文字。
- 面積的原始值與單位要分欄保留，換算結果不覆蓋原值。
- 面積換算（已定）：本筆面積（公頃）＝平方公尺 ÷ 10000，小數 4 位四捨五入；權利面積（公頃）＝本筆面積 × 持分，小數 4 位四捨五入。只用已確認的面積與持分計算，持分看不清就標「待確認」。
- 地號一律當文字處理（保留前導零與點碼格式）。
- 所有權人與耕作人分欄；同姓、同地址、地號相近不自動合併。
- 未確認的 Word 輸出要標「草稿」；簽名蓋章與日期留白。
- 不自動送出正式系統，不要求正式帳號密碼。

## 目標用戶與 UI（詳見 `docs/farmer-ux-agents.md`）

- 主要用戶是**高齡農民**，而且沒有協助者。農民端做：拍照、用「一樣／不一樣」核對謄本資料、回答幾個是非題、選期間、下載同意書、簽名。
- 農民端畫面：內文至少 20px、按鈕高至少 56px、高對比；按鈕一律圖示＋文字；一個畫面一個問題、一個主要按鈕。
- 只用點擊，不用滑動、長按、拖曳。每題都要有「我不確定」和「回上一步」；答「我不確定」的資料維持待確認，同意書維持草稿並列在待辦清單。
- 語音（詳見 `docs/voice-design.md`）：每題都要能聽（唸題目）、能講（語音回答），也都能用按的。語音答案用關鍵詞比對，聽到後必須唸回確認；不保存錄音檔。
- 文字用農民的說法，不用「上傳、同步、提交」這類術語；給農民的訊息用固定範本，不讓 LLM 自由產生。
- 不要求帳號密碼。

## 背景 Agent

- 用固定的狀態流程串接單一職責的 agent（收件、擷取、核對、分派、文件、提醒），不做自由發揮的多 agent 對話。
- agent 只能呼叫被允許的 Action；任何 agent 都不能把欄位標成「已確認」。
- 失敗或不確定一律標「待確認」、列入農民的待辦清單、同意書維持草稿，並寫入操作紀錄；不重試到看起來成功。
- 提醒只發給本案已登記且同意接收通知的人，不聯絡其他第三人。

## MVP 範圍（已定，不再討論；詳見 `docs/farmer-ux-agents.md` 第 6 節）

- 只有農民端：手機網頁，拍照、核對、答題（可聽可講）、選期間、下載同意書。沒有協助者端（Excel 核對表也不做）。
- agent 只做收件、擷取、核對、分派、文件；不做提醒與通知。
- 語音：國語朗讀用 **OpenAI TTS**（`gpt-4o-mini-tts`）事先產生的 mp3（`tools/gen_tts.py --engine openai`、`web/audio/`），找不到才用瀏覽器語音；全部句子用同一個聲音。農民頁會唸的固定句子都要列在 `web/audio/prompts.json`（`tools/collect_prompts.py`，有測試檢查）。國語語音回答。不做台語語音辨識。TTS 金鑰不能出現在前端；只送固定句子，不送姓名、身分證號。
- 只用遮蔽樣本或虛構資料（假謄本在 `data/samples/fake-transcripts/`）。不做 LINE、登入、線上簽名。
- 不在 MVP 範圍的功能，不要主動加進來。

## 個資

- 原始檔只在 `data/raw/`，程式產出只在 `data/output/`，兩者都不進 git。
- `data/samples/` 只能放已遮蔽資料（姓名、身分證、電話、簽名改成代碼：農民 A、土地 A）。
- 不要把真實姓名、身分證號寫進程式碼、測試、commit 訊息或 PR 說明。

## 協作（單人開發）

- 一個人開發，可能同時開 Claude Code 和 Codex。**兩個 AI 不要改同一個檔案**，各自負責一組檔案。
- 直接在 `main` 上小步提交；每次 commit 前先跑測試，`main` 要保持能跑。不要 force push。
- 改動只限當前任務相關的檔案。
- 金鑰只放 `.env`（照 `.env.example`），不要 commit。
- commit 訊息用 `類型: 說明`，例如 `feat: Excel 帶入 Word`、`fix: 地號前導零消失`。

## 技術與指令

- Python 3.10，專案環境在 `.venv`（不進 git）。後端 FastAPI，設計見 `docs/backend-design.md`。
- 安裝：`py -3.10 -m venv .venv`，然後 `.venv\Scripts\python -m pip install -r requirements.txt`
- 啟動：`.venv\Scripts\python -m uvicorn app.main:app --reload --port 8001`，測試台在 http://localhost:8001/
- 測試：`.venv\Scripts\python -m pytest -q`（用假謄本跑完整流程）
- Windows 請設 `PYTHONIOENCODING=utf-8`，避免中文輸出亂碼。
- 修改資料只能透過 `app/actions.py`；新增欄位要改 `app/models.py` 並跑測試。
- LLM：只能透過 `app/llm/harness.py` 呼叫（OpenAI，設計見 `docs/llm-harness.md`）；改提示詞要升 `PROMPT_VERSION` 並跑 `tools/eval_extract.py`，猜測必須為 0。
- 語音合成：`python tools/collect_prompts.py` 收句子 → `python tools/gen_tts.py --engine openai --lang zh --missing` 補音檔（約 2 秒一句）。本機 Qwen3-TTS（`C:\Users\Ray\qwen3-tts\venv`，約 1 分鐘一句）留作備案。
