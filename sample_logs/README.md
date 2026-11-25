# 測試 log 異常分析工具（test-log-analyzer）

> 開發中：目前已完成「log 格式設計」與「模擬 log 產生器」

## 遇到的問題

在顯示器的壓力測試中，測試人員常以目視發現畫面閃爍等異常，但事後需在大量 log 中找出對應時間點與原因，相當耗時。

## 察覺到的潛在問題

- log 量越大，人工越難找、越容易漏看
- 每個人判斷標準不同，結果不一致
- 處理經驗只留在個人腦中，人員異動就會流失
- 不同產品的規格不同，判斷門檻需要能調整

## 解決方式

| 問題 | 解決方式 | 狀態 |
|---|---|---|
| log 量大、容易漏看 | 程式逐行掃描所有 log | 開發中 |
| 判斷標準不一致 | 判斷規則寫在程式中，相同的 log 每次得到相同結果 | 開發中 |
| 經驗流失 | 建立已知問題資料庫，將處理經驗文件化 | 開發中 |
| 門檻需可調整 | 門檻值放在設定檔，不需修改程式 | 開發中 |

## 開發進度

- [x] 階段 1：log 格式設計
- [x] 階段 2：模擬 log 產生器
- [ ] 階段 3：分析工具與報告
- [ ] 階段 4：已知問題資料庫
- [ ] 階段 5：測試與文件

## 模擬資料

所有 log 皆為自行設計的模擬資料，面板型號、數值與規格均為虛構。

### log 格式

```
# test_id=PT-20261125-02
# panel=PNL-X156 resolution=1920x1080 refresh_rate=60
# test_case=video_playback_stress duration_s=600
2026-11-25 10:02:14.995 [INFO] [DISP] FRAME_DONE frame=8100
2026-11-25 10:02:15.000 [ERROR] [DISP] UNDERRUN layer=0 fifo_level=0
```

| 模組 | 說明 | 事件 |
|---|---|---|
| `DISP` | 顯示控制 | `FRAME_DONE`、`UNDERRUN` |
| `DSI` | 顯示傳輸介面 | `DSI_ERR` |
| `BL` | 背光 | `BL_LEVEL`（每秒記錄亮度） |

### 測試情境

| 檔案 | 情境 | 對應的畫面現象 |
|---|---|---|
| `normal.log` | 全部正常 | — |
| `underrun_flicker.log` | 連續 UNDERRUN 造成掉幀，另有 1 次偶發 UNDERRUN | 閃屏 |
| `dsi_error.log` | 傳輸錯誤 | 花屏 |
| `backlight_unstable.log` | 亮度忽高忽低 | 忽明忽暗 |
| `mixed.log` | 多種異常混合，含 1 種未知異常 | — |

### 異常判斷規則

| 異常 | 規則 |
|---|---|
| 掉幀 | 幀間隔超過每幀時間的 1.5 倍（60 Hz 時約 25 ms） |
| UNDERRUN | 1 秒內 3 次以上為「連續異常」，1～2 次為「機率性異常」 |
| DSI 錯誤 | 出現即判定異常 |
| 背光異常 | 亮度偏離目標值超過 10% |
| 未知異常 | ERROR 等級但不在已知清單中的事件 |

## 產生器流程

```mermaid
flowchart TD
    A([開始]) --> B[讀取指令選項]
    B --> C{還有情境？}
    C -- 是 --> D[產生正常事件]
    D --> E[插入該情境的異常]
    E --> F[排序、寫出 log、記錄解答]
    F --> C
    C -- 否 --> G[/寫出解答檔 expected.json/]
    G --> H([結束])
```

## 使用方式

執行需求：Python 3.8 以上。僅使用 Python 標準函式庫，不需另外安裝套件。

```bash
# 產生 5 份模擬 log 與解答檔（預設 600 秒）
python sample_logs/generator.py

# 調整測試長度為 1 小時
python sample_logs/generator.py --duration 3600
```

| 選項 | 預設值 | 說明 |
|---|---|---|
| `--duration` | 600 | 測試長度（秒） |
| `--seed` | 42 | 隨機種子，相同種子產生相同的 log |
| `--outdir` | sample_logs | 輸出資料夾 |

## 設計決策

- **使用模擬資料**：不使用任何真實資料，避免資料外流疑慮
- **測試長度預設 600 秒**：約 36,000 行，資料量足以呈現人工檢查的困難，範例檔也不會過大；實際長度可依需求調整
- **固定隨機種子**：每次產生的 log 完全相同，結果可重現
- **產生解答檔 `expected.json`**：記錄每個異常的類型與行號，用來自動驗證分析工具是否全部找到、有無誤判
- **掉幀門檻自動計算**：門檻由更新率推算，更換更新率時不需另外修改

## 開發方式

本專案使用 AI 工具（Claude）協助開發。

- 問題定義、判斷規則與設計決策為自行規劃
- 程式碼由 AI 協助產生，逐段理解後納入
- 考量 AI 的輸出不一定每次一致，異常判斷全部由程式規則執行，確保相同的 log 每次都得到相同的結果

## English Summary

A tool for analyzing display stress-test logs. It parses large log files, detects anomalies such as frame drops, underruns, and transmission errors using rule-based checks, and matches them against a known-issue database to produce an analysis report. All sample data is synthetic. (Work in progress)

## 作者

**Arista Wu**（[@codingarista](https://github.com/codingarista)）
B.S. in Computer Science｜Interests: Japanese, AI