# 官方參考資料

## land_sections.csv — 全國土地段名代碼

- 來源：內政部地政司「土地段名代碼（ＡＰＩ）」<https://data.gov.tw/dataset/122674>
- 下載網址：<https://lisp.land.moi.gov.tw/MoiMMSv2/SectionList.ashx>（JSON）
- 授權：政府資料開放授權條款－第1版
- 下載日期：2026-11-07（16,275 筆，366 個鄉鎮市區／地政事務所單位）
- 欄位：county 縣市、township 鄉鎮市區、office 地政事務所、office_code、town_code、section 段名（不含「段」）、subsection 小段（不含「小段」）、section_code 段代碼、comment 原始備註（增編／調整／更正…）
- 只保留上述欄位，內容未修改（原始資料「台南市／臺南市」混用，比對時才正規化）。
- 重新產生：`.venv\Scripts\python -m app.refdata.fetch_sections`

用途：`app/refdata/sections.py` 比對擷取到的段名是否在官方清單，對不上只加警示，不改值。
