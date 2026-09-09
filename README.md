# 工具使用指南：opencv_camera_api_test.py、run_manual_suite.py 與官方測試腳本

> 本目錄工具的**現行完整用法**：
>
> | 工具 | 性質 | 一句話定位 |
> |---|---|---|
> | **`opencv_camera_api_test.py`** | 全自動 CLI（單檔、零配置） | 「這台機器的 OpenCV camera API 是否齊全且正常？」→ 自動產出三種報告 |
> | **`run_manual_suite.py`** | 半自動互動驅動 | 「需要人手操作/目視判斷的 6 個測項」→ 自動量測取證，你只做最終判定 |
> | **`official/`** | 官方 gtest 套件一鍵腳本 ×2 | 「OpenCV 函式庫層官方測試」→ 建置環境 + 執行 + Excel 報告 |
>
> 所有指令與輸出均為本機（C920 @ /dev/video2、OpenCV 4.5.4）實際驗證過的結果。

---

## 目錄結構

```
camera_toolkit/
├── README.md            本指南
├── run_config.yaml      執行設定（device/backend/report_root/…）
├── run_camera_tests.py  互動總指揮：讀設定→確認→建時間戳報告夾→依序執行→整合
├── auto/                自動化 API 涵蓋率測試（Python）
│   └── opencv_camera_api_test.py
├── auto_cpp/            同套檢查的 C++ 版（連結 5.1.0-dev 建置）
│   ├── CMakeLists.txt / src/main.cpp / include/cap_prop_table.hpp
│   └── tools/gen_cap_prop_table.py
├── manual_cpp/          手動套件的 C++ 版（6 項自動取證 + 判定提示）
│   ├── CMakeLists.txt / src/main.cpp / run.sh（自動建置+執行）
│   └── 輸出 report_manual_cpp.json
├── manual/              手動測項套件（驅動 + manifest + 4 個量測助手）
│   ├── run_manual_suite.py / manifest_manual.yaml
│   └── *_visual_check.py ×3、usb_unplug_reconnect_test.py
├── generate_combined_report.py  三區結果整合 → combined_report.xlsx
├── official/            官方 gtest 套件一鍵腳本
│   ├── setup_official_videoio_env.py
│   └── run_official_videoio_test.py
├── build/ opencv/ opencv_extra/   官方建置環境（體積大，勿隨意搬移）
└── report/ manual_evidence/ …      歷史輸出
```

> 各區指令請在**對應資料夾內**執行，或使用下方範例的相對路徑（如 `auto/opencv_camera_api_test.py`）。

---

1. [opencv_camera_api_test.py（自動化）](#1-opencv_camera_api_testpy自動化)
2. [run_manual_suite.py（手動套件驅動）](#2-run_manual_suitepy手動套件驅動)
3. [official/（官方測試套件）](#3-official--官方-gtest-套件腳本)
4. [建議工作流程](#4-建議工作流程)

---

## 1. auto/ — opencv_camera_api_test.py（自動化）

### 1.1 快速開始

```bash
# 標準用法：指定裝置與 backend（強烈建議永遠明確指定 backend）
python3 auto/opencv_camera_api_test.py --device /dev/video2 --backend V4L2

# 只看會測哪些 API（inventory，不碰相機）
python3 auto/opencv_camera_api_test.py --list-only
```

執行後自動在 `--outdir`（預設 `./report`）產出三份報告：

| 檔案 | 面向 |
|---|---|
| `report_auto.md` | 人類閱讀（分組表格、SKIP 原因、涵蓋率） |
| `report_auto.json` | 機器可讀（CI parse `summary.exit_code` 等） |
| `report_auto.xlsx` | 管理/轉寄用 Excel（Summary / All Results / Skip Reasons / Metrics 四表） |

> 預設輸出資料夾：`./report/new/`

### 1.2 完整參數

| 參數 | 預設 | 說明 |
|---|---|---|
| `--device` | `0` | 相機 index 或 `/dev/videoN`；GSTREAMER/FFMPEG 下可用 pipeline 字串或 URL |
| `--backend` | `ANY` | `ANY` / `V4L2` / `GSTREAMER` / `FFMPEG`。**正式使用請明確指定**——ANY 可能被 GStreamer 搶走導致屬性全 SKIP（實測教訓） |
| `--outdir` | `./report` | 三份報告 + `writer_test.avi` 的輸出目錄 |
| `--frames N` | `30` | read() 迴圈幀數（成功率統計 + FPS 實測樣本） |
| `--width/--height/--fps` | None | 開啟後套用的解析度/幀率要求（會回讀驗證） |
| `--list-only` | off | 只印 API 盤點（46+ 計畫項、方法、registry 函式、CAP_PROP 家族統計） |
| `--no-full-sweep` | off | 跳過 F 組 CAP_PROP 全列舉掃描（省時） |
| `--no-xlsx` | off | 不產出 Excel（openpyxl 未安裝時本來就會自動略過） |
| `--json PATH` | None | 額外複製一份 JSON 到指定路徑 |

### 1.3 測試組（A~G）

| 組 | 內容 | 數量 |
|---|---|---|
| A | Environment：版本、build flags、videoio_registry 函式 ×8 | 11 |
| B | Lifecycle：建構/open/isOpened/getBackendName/exception mode/waitAny/負向案例/open-only 參數預檢/**backend_any_vs_v4l2 對照**/grab/retrieve/read 迴圈/release | 13 |
| C | 核心屬性 set→get（WIDTH/HEIGHT/FPS/FOURCC/BUFFERSIZE/AUTO_EXPOSURE/EXPOSURE/GAIN/FORMAT/MODE/CONVERT_RGB） | 11 |
| D | 影像品質：幀存在/尺寸/std 變異/凍結偵測 | 4 |
| E | VideoWriter 方法級：fourcc/建構/isOpened/getBackendName/get/set/write/release/readback + VIDEOWRITER_PROP_* 盤點 | 10 |
| F | CAP_PROP 全列舉掃描（261 唯一 id + 25 已知上游常數缺席標記） | 動態 ~286 |
| G | Driver cross-validation：協商格式 vs `v4l2-ctl` 宣傳清單 | 1 |

### 1.4 判定語義與 exit code

| Status | 意義 | 典型例子 |
|---|---|---|
| PASS | 有行為證據的通過 | set 後 get 回讀一致；read 成功率 100% |
| FAIL | 行為錯誤，需要修 | 讀取成功率 <80%、全黑畫面、協商了驅動沒宣傳的格式 |
| WARN | 有執行但存疑 | **no-op roundtrip（0→0，支援未證明）**、roundtrip 漂移、CAP_ANY 分歧 |
| SKIP | 無法執行，附原因 | 驅動拒絕 set、by-design（他牌硬體屬性）、常數此版不存在 |

```text
exit code: 0=全部通過 │ 1=有 FAIL │ 2=無相機（全 SKIP 降級）│ 3=cv2 未安裝
```

### 1.5 涵蓋率怎麼讀

```text
coverage(core) : 計畫檢查項（A~G plan，51 項）被執行的比例
coverage(full) : core ∪ 方法 ∪ registry ∪ CAP_PROP 全表面（~367）被探測的比例
skipped-by-design : 其他 backend 家族屬性（不適用 ≠ 失敗）
passed ratio   : 探測過的部分通過比例 —— 低於 100% 才是真問題
```

### 1.6 常見場景配方

```bash
# ① 新 USB 相機開箱檢查（C920 在 video2 的例子）
python3 auto/opencv_camera_api_test.py --device /dev/video2 --backend V4L2 \
  --width 1280 --height 720 --fps 30 --frames 60

# ② 高解析度驗證（記得 MJPG 由工具內部處理順序陷阱？否——工具會先測 YUYV；
#    若要驗 1080p30 請確認相機支援 MJPG，見 02 篇 §6）
python3 auto/opencv_camera_api_test.py --device 2 --backend V4L2 --width 1920 --height 1080

# ③ Backend 能力剖面對照（同一顆相機各跑一次）
python3 auto/opencv_camera_api_test.py --device 2 --backend V4L2    --outdir r_v4l2
python3 auto/opencv_camera_api_test.py --device 2 --backend GSTREAMER --outdir r_gst

# ④ IP 攝影機 / 影片檔
python3 auto/opencv_camera_api_test.py --backend FFMPEG --device "rtsp://user:pw@ip/stream"

# ⑤ CI 無相機 runner（v4l2loopback 可讓 exit 2 變 0，見 05 篇 §6.2）
python3 auto/opencv_camera_api_test.py --device 0; echo "exit=$?"

# ⑥ API 盤點報告（家族統計，回答「上游有哪些屬性」）
python3 auto/opencv_camera_api_test.py --list-only
```

### 1.7 結果解讀速查

| 看到 | 解讀 |
|---|---|
| `WARN ... no-op roundtrip (0 -> 0)` | 驅動接受 set 但值沒變——API 活著但效果未證明，接真實場景時用 `v4l2-ctl -C <ctrl>` 對照 |
| `SKIP unsupported (get=0, set rejected)` | 相機真的沒有這個控制項（如固定鏡頭無 ZOOM） |
| `SKIP by-design: Ximea-only...` | 其他硬體世界的屬性，不適用≠失敗 |
| `SKIP constant absent in this cv2 build` | 上游新版常數，升級 OpenCV 後自動納入探測 |
| `[B] backend_any_vs_v4l2 WARN divergence` | **CAP_ANY 被別的 backend 搶走**——正式碼務必明確指定 backend |

---

## 2. manual/ — run_manual_suite.py（手動套件驅動）

### 2.1 它做什麼

驅動 6 個「本質上需要人工判斷」的測項（manifest 來自 `../opencv_claude/camera_api_test/manifest_manual.yaml`）。每項流程：

```
自動產生客觀證據（呼叫輔助腳本量測 + 存快照）
        ↓
顯示數據摘要
        ↓
你輸入最終判定 p(PASS)/f(FAIL)/s(SKIP) ＋ 選填備註
        ↓
合併寫入 report/new/report_manual.json + report/new/report_manual.xlsx
```

### 2.2 六個測項

| # | test_ref | 自動化部分 | 你要做的 |
|---|---|---|---|
| 1 | device_index_physical_mapping | 列舉 sysfs 全部節點並逐一試開，標出 CAPTURE/metadata node | 確認 target 就是你以為的那顆 |
| 2 | exposure_visual_check | AUTO_EXPOSURE 切換 + EXPOSURE 掃描，量亮度、存快照 | 看快照確認亮度方向 |
| 3 | autofocus_visual_check | FOCUS 掃描（Laplacian 清晰度）+ ZOOM 掃描 | 看快照確認清晰度變化 |
| 4 | white_balance_visual_check | WB_TEMPERATURE 掃描（RGB cast 指標） | 看快照確認色調偏移方向 |
| 5 | real_usb_unplug_reconnect | 跑重連工具開時間窗，**即時串流 log + 大字提示何時拔/插線** | 真的拔插 USB |
| 6 | long_duration_stability | 定時記錄 RSS/失敗率趨勢 | 事後判讀曲線 |

### 2.3 指令

```bash
# 清單預覽（不執行）
python3 manual/run_manual_suite.py --list

# 全套互動（依序 6 項）
python3 manual/run_manual_suite.py --device /dev/video2

# 單項執行（結果累積合併進同一份報告）
python3 manual/run_manual_suite.py --item exposure_visual_check

# 常用選項
--device /dev/video2      # 主相機
--reconnect-window 60     # 第 5 項的拔插作業視窗秒數（預設 45）
--long-run 30             # 第 6 項長跑分鐘數（未給則該項 SKIP）
--answer s                # 非互動模式（CI/煙霧測試）：所有項目用同一答案
--excel-dir report/new    # Excel 輸出資料夾（預設 report/new）
--report PATH             # JSON 報告位置（預設 ./report/new/report_manual.json = 執行時 cwd）
--evidence DIR            # 快照/log 證據目錄（預設 ./manual_evidence）
```

### 2.4 輸出位置

| 檔案 | 位置 |
|---|---|
| 手動判定報告 | `report/new/report_manual.json`（cwd 相對；與 opencv_claude 的 `manual_test_runner.py` 同 schema） |
| Excel 報告 | `report/new/report_manual.xlsx` |
| 各測項證據 | `manual_evidence/`（reconnect 子目錄含 events.jsonl + summary.json）、`exp_check/`、`focus_check/`、`wb_check/` |

### 2.5 與總涵蓋率報告合併

```bash
cd ../opencv_claude/camera_api_test
python3 report_generator.py report_c920.json <手動報告的絕對或相對路徑>
# → 產出 coverage_report.md，人工章節與自動化章節合成完整健康檢查
```

### 2.6 目前記錄狀態（2026-08-24）

```text
real_usb_unplug_reconnect = PASS   ← 實機拔插完成
其餘 5 項                  = SKIP   ← 待正式判定（工具已就緒）
```

---

## 3. official/ — 官方 gtest 套件腳本

OpenCV 原始碼內建 gtest 測試 `opencv_test_videoio`（581 案例），驗證**函式庫層**正確性（與前兩個工具驗「你的相機組合」互補）。兩支腳本把它自動化，詳細說明見該資料夾的 `README.md`。

### 3.1 兩支腳本

| 腳本 | 用途 |
|---|---|
| `setup_official_videoio_env.sh` | 建置環境：clone OpenCV + 測試媒體 → CMake → 編譯出 `build/bin/opencv_test_videoio`；已存在的項目會詢問是否重做（Enter=保留、y=重做、`-y` 全重做） |
| `run_official_videoio_test.sh` | 執行測試並產出 Excel 報告；exit code 與測試結果同步（0=全過、1=有 FAIL、2=環境錯誤） |

### 3.2 指令

```bash
cd official

# 第一次：建置環境（預設建在當下目錄；-d 可指定）
./setup_official_videoio_env.sh -d ~/ocv_env -j 8

# 全套 581 項測試
./run_official_videoio_test.sh -e ~/ocv_env -o ./report_full

# 打 C920 相機，只跑 V4L2 類別
./run_official_videoio_test.sh -e ~/ocv_env \
    -d /dev/video2 -f '*videoio_v4l2*' -o ./rpt_c920

# 只跑 FFmpeg 串流讀取類
./run_official_videoio_test.sh -e ~/ocv_env \
    -f 'videoio/stream_capture*' -o ./rpt_stream
```

參數速查：

| run 腳本參數 | 說明 |
|---|---|
| `-e ENV_DIR` | setup 產出的環境根目錄 |
| `-f FILTER` | gtest filter（如 `'*videoio_v4l2*'`） |
| `-d DEVICE` | 相機裝置；**未給時 v4l2 測試會靜默跳過（顯示 OK 但 0ms）** |
| `-o OUTDIR` | 報告輸出目錄（預設 `./report/new`） |
| `-x "ARGS"` | 額外參數直傳 gtest |

### 3.3 輸出

| 檔案 | 內容 |
|---|---|
| `<outdir>/report_offical.xlsx` | Summary（環境+統計）/ Failed Tests（名稱+錯誤細節）/ All Tests（全案例+耗時） |
| `<outdir>/videoio_gtest.log` | gtest 原始完整輸出 |

解讀要點：

- **真實相機上的能力性 FAIL 是正常的**——官方 V4L2 格式測試以 kernel 虛擬裝置（vivid，全格式接受）為基準；打 C920 時 21 格式中只有 YUYV/UYVY 過，其餘為相機能力邊界
- 未給 `-d` 時 v4l2 測試被靜默跳過，「全綠」不代表有測到相機
- FFMPEG backend 相關案例需系統有 libavcodec-dev 才會編入支援

---

## 4. 一鍵執行（推薦入口）

```bash
python3 run_camera_tests.py                 # 互動式：顯示 run_config.yaml 設定
                                           # → 可修改 → 選套件(1 auto/2 manual/
                                           #   3 official/4 all，預設 4) → 建立
                                           # report/<YYYY-MM-DD-HHMMSS>/ → 執行 → 整合
                                           # （選 official 時自動預檢環境，
                                           #   缺件會中斷並提示安裝指令）
python3 run_camera_tests.py --dry-run       # 只看會執行的指令
python3 run_camera_tests.py --config my.yaml
```

設定檔欄位：`device` / `backend` / `report_root` / `official_env_dir` /
`combined_report`；CLI 與互動輸入永遠覆蓋檔案值。首次執行若無設定檔會自動生成。

---

## 5. 建議工作流程

### 4.0 三區結果一鍵整合

三區各自跑完後，產出統一 Excel：

```bash
python3 generate_combined_report.py          # 預設讀 report/new/ 三份來源
# exit 0=無 FAIL │ 1=有 FAIL │ 2=找不到任何結果檔
```

輸出 `report/new/combined_report.xlsx`：Summary（並排統計+整體判定+行動提示）、
Auto（逐檢查列）、Manual（判定+證據備註）、Official（gtest 逐案例，含耗時）。
官方失敗會自動歸因：`videoio_v4l2.formats/*` 標記為相機格式能力邊界。

### 4.1 新板卡/新相機開箱

```bash
# Step 1 驅動層（04 篇 §2）
v4l2-ctl --list-devices && v4l2-ctl -d /dev/videoN --list-formats-ext

# Step 2 OpenCV 層自動化
python3 auto/opencv_camera_api_test.py --device /dev/videoN --backend V4L2 --frames 60

# Step 3 手動套件（目視類驗證）
python3 manual/run_manual_suite.py --item exposure_visual_check
python3 manual/run_manual_suite.py --item autofocus_visual_check
python3 manual/run_manual_suite.py --item white_balance_visual_check
python3 manual/run_manual_suite.py --item real_usb_unplug_reconnect   # 需要你在場拔插

# Step 4 官方函式庫層測試（可與 Step 1~3 並行建置）
cd official
./setup_official_videoio_env.sh -d ~/ocv_env
./run_official_videoio_test.sh -e ~/ocv_env -d /dev/videoN -o ./rpt_board

# Step 5 合併報告
python3 ../opencv_claude/camera_api_test/report_generator.py \
  report_c920.json report/new/report_manual.json
```

### 4.2 驅動/OpenCV 升級後回歸

重跑 Step 2（自動化）+ Step 4（官方 gtest）——前者比對相機組合的涵蓋率與判定，後者確認新版本函式庫本身乾淨；F 組會自動列舉新版新增的常數。

### 4.3 本目錄工具清單

| 檔案 | 用途 |
|---|---|
| `opencv_camera_api_test.py` | 自動化 API 涵蓋率測試主工具 |
| `run_manual_suite.py` | 手動測項統一驅動 |
| `usb_unplug_reconnect_test.py` | 拔插重連專項（也被 run_manual_suite 第 5 項呼叫） |
| `exposure_visual_check.py` / `autofocus_visual_check.py` / `white_balance_visual_check.py` | 三個目視項目的獨立量測助手（也可單獨用） |
| `official/` | 官方 gtest 測試一鍵腳本 ×2 + 專屬 README |

---

## 6. 預編譯包：先編好 → 打包 → 目標機直跑（含 cross compile）

C++ 套件（`auto_cpp`、`manual_cpp`）與官方 `opencv_test_videoio` 採 selfbuild。
先在一台機器上編好，打成 relocatable tarball，目標機解包後**不重編直接執行**。
`testdata` 不進包，改由目標機安裝時再抓（full 389M）。

### 6.1 Makefile 一覽（預設原生，`ARCH=aarch64` 切 cross）

| 指令 | 作用 | 產物 |
|---|---|---|
| `make prebuild` | 原生全編（opencv + auto_cpp + manual_cpp） | `build/latest/`、`auto_cpp/build/`、`manual_cpp/build/` |
| `make verify` | 原生驗證（`ldd` + smoke） | PASS 才往下走 |
| `make prebuild ARCH=aarch64` | cross 全編（x86_64 → aarch64） | `build/aarch64/`、`auto_cpp/build-aarch64/`、`manual_cpp/build-aarch64/` |
| `make verify-cross ARCH=aarch64` | cross 驗證（`file` + `readelf` + qemu smoke） | PASS 才打包 |
| `make package [ARCH=...]` | 打包（不含 testdata/source） | `dist/camera-toolkit-<arch>-*.tar.gz`（x86 實測 28M、arm64 實測 11M） |
| `make install [ARCH=...]` | 打包 + 組出本地 `./install/`（免 sudo、可直接執行，見 6.4） | `./install/` |
| `make install-target` | 印出目標板上的安裝指令（需 sudo） | 提示文字 |

### 6.2 Cross compile 前置（x86_64 → aarch64，一次就好）

```bash
bash scripts/build_prebuilt.sh --arch aarch64 --install-deps   # 需 sudo：
# dpkg 加 arm64 架構 → 加 ports.ubuntu.com 源 → 裝 aarch64-linux-gnu-g++ →
# 裝 libavcodec/format/util/swscale、libtiff、libopenexr、libyaml-cpp 的 :arm64 dev 包
```

原理：`cmake/toolchain-aarch64.cmake`（`SYSTEM_NAME/PROCESSOR` + triple-prefixed compiler
+ `FIND_ROOT_MODE_*` + `PKG_CONFIG_SYSROOT` + 沿用 `$ORIGIN` RPATH），
搭配 `qemu-aarch64-static` 做 smoke。FFmpeg 政策是**缺件就報錯停下**，不允許
`-DWITH_FFMPEG=OFF` 降級（videoio 會被閹割）。

注意：builder 與目標機的 Ubuntu 主版本必須一致（同為 noble 24.04），
否則 `libavcodec.so.60` / `libtiff.so.6` 等版號又會對不上（見 6.5）。

### 6.3 目標板安裝（arm64 板上，需 sudo）

```bash
sudo bash scripts/install_prebuilt.sh \
  --tarball dist/camera-toolkit-aarch64-*.tar.gz \
  --prefix /opt/camera-toolkit --fetch-testdata full --yes
# 做什麼：apt 裝 runtime libs → 解包 → arch 閘門（x86 包拒上 arm64）→
# 抓 testdata（full/slim/skip）→ smoke
```

`--fetch-testdata full` 會 `git sparse-checkout testdata/cv + testdata/highgui`；
無外網的現場改用預包 testdata 或 `--fetch-testdata skip`。

### 6.4 直接執行（不重編、不放 /opt 也行）

**可以。`install/`（或 `/opt/camera-toolkit`）本身就是 relocatable 包，
在資料夾內直接執行即可**，靠兩層機制：cross 件是 `$ORIGIN` RPATH，
native 件靠 `setup_vars.sh` 的 `LD_LIBRARY_PATH` fallback；
`scripts/run_test_*.sh` 偵測到自己身處包內（`../bin/` 存在）會自動設
`PREBUILT_ROOT` 並跳過 `git/cmake/apt` 重編：

```bash
./install/scripts/run_test_auto.sh --device /dev/video0 --no-build
./install/scripts/run_test_manual.sh -d /dev/video0 --outdir ./rpt
python3 ./install/scripts/run_official_videoio_test.py \
  -e ./install/opencv_extra -d /dev/video0 -o ./rpt   # 需先 --fetch-testdata
```

`--no-build` / `PREBUILT_ROOT=...` / `SKIP_BUILD=1` 三者任一都會進入 prebuilt 模式；
缺 binary 或 `ldd` 有 `not found` 會直接 exit 2 而不是默默重編。

### 6.5 背景：`.so` 版號坑

`build/latest` 曾是 Ubuntu20 殘留（link `libavcodec.so.58` / `libtiff.so.5` /
`IlmImf-2_5`），在 Ubuntu24（`libavcodec.so.60` / `libtiff.so.6` / `OpenEXR-3_1`）
上 `ldd` 全滅。解法是在目標同版本 OS 上**砍掉重編**（`build_prebuilt.sh`
內建 stale-ABI 拒絕門），不要增量編。新包另有兩處防線：
`VERSION.json`（opencv commit + ffmpeg 版號 + arch）與 install 時的 arch 閘門。

### 6.6 範例：外層 `example/Makefile`（佈局 `example/camera_toolkit`）

若 toolkit 被包進上層專案（`example/camera_toolkit`），外層 Makefile 只需委派：

```make
# example/Makefile — thin wrapper, 實際工作全在 camera_toolkit/
TOOLKIT_DIR := $(CURDIR)/camera_toolkit
ARCH ?= native
JOBS ?= $(shell nproc)
INSTALL_DIR ?= $(CURDIR)/install

.PHONY: prebuild package verify verify-cross install help
help:
	@echo "targets: prebuild | package | verify | verify-cross | install  (ARCH=native|aarch64)"

prebuild:
	$(MAKE) -C $(TOOLKIT_DIR) prebuild ARCH=$(ARCH) JOBS=$(JOBS)

package:
	$(MAKE) -C $(TOOLKIT_DIR) package ARCH=$(ARCH)

verify:
	$(MAKE) -C $(TOOLKIT_DIR) verify

verify-cross:
	$(MAKE) -C $(TOOLKIT_DIR) verify-cross ARCH=aarch64

install:
	$(MAKE) -C $(TOOLKIT_DIR) install ARCH=$(ARCH) INSTALL_DIR=$(INSTALL_DIR)
```

```bash
make -C example prebuild ARCH=aarch64
make -C example verify-cross ARCH=aarch64
make -C example install ARCH=aarch64   # 產物在 example/install/，dist 維持在 camera_toolkit/dist/
```

要點：`$(MAKE) -C` 會把 cwd 切進 `camera_toolkit/`，內層相對路徑不用改；
只有 `INSTALL_DIR` 必須給絕對路徑（`$(CURDIR)/install`），否則會被內層相對解讀。
