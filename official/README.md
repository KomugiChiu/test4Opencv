# OpenCV 官方 videoio 測試腳本

兩支腳本負責 OpenCV 官方測試程式 `opencv_test_videoio` 的自動化：
**建置環境 → 執行測試 → 產出 Excel 報告**。（純 Python，僅需 `python3` + `git/cmake/make/g++`）

```
setup_official_videoio_env.py   建置環境（clone、測試媒體、編譯）
run_official_videoio_test.py    執行測試並產出 report.xlsx
```

---

## 1. `setup_official_videoio_env.py` — 建置環境

做四件事：clone OpenCV 原始碼、抓測試媒體檔（opencv_extra sparse checkout）、CMake 配置、編譯出 `build/bin/opencv_test_videoio`。

```bash
python3 setup_official_videoio_env.py [選項]
```

| 選項 | 說明 | 預設 |
|---|---|---|
| `-d, --dir DIR` | 目標資料夾 | **執行指令當下的目錄** |
| `-j, --jobs N` | 編譯平行數 | nproc |
| `-b, --branch BRANCH` | opencv 分支 | repo 預設 |
| `-B, --extra-branch BRANCH` | opencv_extra 分支 | repo 預設 |
| `-y, --yes` | 所有「重做？」詢問自動回答 yes | 關閉 |

**已存在的項目會互動詢問**：

```
Found existing opencv/ clone. Redo it? [y/N]
```

- 按 **Enter** 或輸入 N → 保留既有（跳過）
- 輸入 **y** → 刪除重做
- `-y` → 全部直接重做；非互動 shell（CI）中 Enter/EOF = 保留

產出的目錄結構：

```
<目標資料夾>/
├── opencv/           # 原始碼
├── opencv_extra/     # 測試媒體（testdata/cv + testdata/highgui）
└── build/
    └── bin/opencv_test_videoio   # 測試執行檔
```

耗時參考：12 核機器約 5 分鐘（clone ~1 分 + build ~4 分）。

## 2. `run_official_videoio_test.py` — 執行測試 + Excel 報告

```bash
python3 run_official_videoio_test.py [選項]
```

| 選項 | 說明 | 預設 |
|---|---|---|
| `-e, --env ENV_DIR` | 第 1 步建置的環境根目錄 | 當下目錄 |
| `-f, --filter FILTER` | gtest filter，如 `'*videoio_v4l2*'` | 全部 581 項 |
| `-d, --device DEVICE` | 相機裝置路徑，自動設 `OPENCV_TEST_V4L2_VIVID_DEVICE` | 不設（v4l2 測試靜默跳過） |
| `-o, --outdir OUTDIR` | 報告輸出目錄 | `./official_report` |
| `-x, --extra "ARGS"` | 額外參數直傳測試二進位 | 無 |

**輸出**（在 `--outdir` 指定目錄）：

| 檔案 | 內容 |
|---|---|
| `report.xlsx` | Summary（環境+統計）/ Failed Tests（失敗名稱+錯誤細節）/ All Tests（全部案例+耗時） |
| `videoio_gtest.log` | gtest 原始完整輸出 |

**Exit code 與測試結果同步**：0=全過、1=有 FAIL、2=環境錯誤（找不到 binary 等）。CI 可直接判斷。

## 3. 典型流程

```bash
# 第一次：建置（之後重跑會問是否重做）
python3 setup_official_videoio_env.py -d ~/ocv_env

# 全套測試（581 項）
python3 run_official_videoio_test.py -e ~/ocv_env

# 打相機，只跑 V4L2 類別測試
python3 run_official_videoio_test.py -e ~/ocv_env \
    -d /dev/video0 -f '*videoio_v4l2*' -o ./rpt_cam

# 只跑 FFmpeg backend 的串流測試
python3 run_official_videoio_test.py -e ~/ocv_env \
    -f 'videoio/stream_capture*FFMPEG*' -o ./rpt_ffmpeg
```

## 4. 注意事項

- **兩種 v4l2 結果要分清**：
  - 未給 `-d` 相機 → v4l2 測試顯示 OK 但 0ms（內部靜默跳過，沒有真的測）
  - 有相機但格式不支援 → 真實 FAIL（如 C920 對 Bayer/Y16 回拒），屬硬體能力邊界而非 bug
- 相機被拔除時會出現大量 `cap.open(...) = false` 的 0ms FAIL——先確認裝置存在（`ls /dev/video*`）
- `-d` 指向真實相機時，測試期間會佔用裝置；先關掉其他取像程式
- openpyxl 未安裝時腳本會嘗試 `pip install --user openpyxl`，仍失敗則保留原始 log
- ARM64 板上流程相同，編譯時間依核數拉長
