# 法律注意事項（規則式提醒）

## 目的

從謄本資料與農民的回答，找出「簽同意書前要特別留意」的情況，
變成：給農民的固定範本問題（可聽可講）＋ 給協助者的待辦。程式在 `app/agents/legal.py`。

## 立場

- **提醒不是判斷**：系統只偵測情況，不下任何法律結論，也不會因此自動擋下或放行。
- 法條參考只是線索，字串一律以「（待法律專業確認）」結尾。
- 白皮書原列「法規判斷」不在範圍；這裡只做提醒，判斷交給協助者與法律專業。
- 給農民的文字是固定範本，不由 LLM 產生；不出現其他共有人的姓名、證號、地址。
- 每個注意事項都要協助者處理（寫處理說明）才會從「還不能出正式版」清單消失；agent 與農民都不能代為處理。

## 規則

| id | 觸發條件 | 給協助者 | 農民題目（id／題型） | 參考（待法律專業確認） |
|---|---|---|---|---|
| `coowner` | 任一筆土地有 2 筆以上所有權登記 | 共有土地：需確認其他共有人是否同意或一起簽署 | `L-coowner`／yesno：這筆地還有其他地主，他們知道你要簽同意書嗎？（知道／不知道／我不確定） | 民法第 818、820 條；土地法第 34 條之 1 |
| `lease` | 農民第 2 題答「別人」 | 有他人耕作：需確認是否有耕地租約（例如三七五租約），會影響由誰簽 | `L-lease`／have：你跟種田的人，有沒有簽租約？（有／沒有／我不確定） | 耕地三七五減租條例 |
| `unclear-share` | 權利範圍 AI 讀不到或被標「看不清」，且協助者還沒確認該欄位 | 權利範圍看不清：無法判斷簽署人的權利是否完整 | 無（只給協助者） | 民法第 817、819 條（應有部分） |

- 注意事項每次都從目前資料重新推出（`legal.issues(case)`），只儲存農民的回答（`case.answers`）與協助者的處理紀錄（`case.legal_notes`）。
- 農民對法律題答「不知道／沒有」或「我不確定」時，分派 agent 加一筆協助者任務。
- 新增規則：在 `legal.py` 寫一個回傳 `LegalIssue | None` 的函式，加進 `RULES`。

## API 變動

- `GET /api/f/{token}`：新增 `lands[].area_raw / area_unit / page`、`photos`（每頁最後一張合格照片的網址）、`helper`（`HELPER_NAME`、`HELPER_PHONE`）；`questions` 改為完整題目（`id, text, say, kind, options[{value,label}], why, legal`），q1–q3 之後接目前有效的法律題。
- `GET /api/f/{token}/photos/{page}`：回傳本案該頁最後一張合格照片，否則 404。
- `POST /api/f/{token}/photos`：回應新增 `checks`（`bright` 夠亮／有點暗、`sharp` 清楚／有點糊；打不開時為空陣列）。
- `POST /api/f/{token}/answers`：可回答目前有效的法律題（yes／no／unsure）；回應為 `{ok, answers, questions}`。
- `GET /api/cases/{id}`：新增 `legal`：`[{id, title, detail, reference, question_id, answer_label, resolved, note}]`。
- `POST /api/cases/{id}/legal/{issue_id}/resolve`，body `{note}`：協助者標記已處理；注意事項目前不存在時 404。
