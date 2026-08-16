# Multi-Agent Synthesizer

雙本地 LLM 協作框架，三種可選模式，適用於任何 OpenAI API 相容的本地伺服器
（llama.cpp、LM Studio、vLLM、Ollama…）。

## 三種協作模式

### 模式一 `synthesize`：並行生成 + 融合大腦（預設）

```
                ┌──> 模型 A (UI / 視覺專家) ──┐
任務 prompt ────┤                            ├──> 融合節點 (首席架構師) ──> 最終成果
                └──> 模型 B (架構 / 狀態專家)─┘
                     (asyncio.gather 並行)
```

兩模型同時作答（並行，只需等最慢的一個），第三節點融合雙方優點。

### 模式二 `critique`：互相審查 (Critic & Refine)

```
任務 ──> 模型 B 產架構初稿 ──> 模型 A 以 UI/介面視角審查、抓漏、輸出修正版
```

開發者與測試者的關係：不需要第三次生成，由審查者直接輸出整合修正版。

加 `--reverse` 可反轉方向：模型 A 先產 UI 初稿，模型 B 以架構/狀態管理視角審查修正。
兩個方向各跑一次、互相比對，等於完整的「雙向審查」。

### 模式三 `pipeline`：專長分工管線

```
任務 ──> 模型 A 拆解成結構化 JSON 規格 ──> 模型 B 依規格實作狀態管理與邏輯 ──> 最終成果
```

不讓兩個模型做同一件事：A 負責需求/介面解析，B 負責核心邏輯實作。
最終輸出是一份：B 依規格實作的完整可執行程式碼（`*-final.md`）；
JSON 規格本身也會存檔（`*-spec.md`）作為中間產物，方便檢查或復用。

## 安裝

```bash
pip install -r requirements.txt
cp config.example.toml config.toml   # 填入你自己的端點與模型名稱
```

## 設定

`config.toml`（已 gitignore，不會進 repo）分四段：

| 區段 | 用途 |
|---|---|
| `[qwen]` | 模型 A — UI / 視覺專家的端點、模型名、system prompt |
| `[muse]` | 模型 B — 架構 / 狀態管理專家 |
| `[synthesizer]` | 融合節點（建議用你手上推理最強的模型） |
| `[generation]` | temperature / max_tokens |

模型名稱可用 `curl http://<host>:<port>/v1/models` 查詢。

**單機 VRAM 不足？** 把 `[qwen]` 與 `[muse]` 指向同一個伺服器、同一個模型，
只靠不同的 system_prompt 區分角色，一樣有「思維碰撞 → 融合」的效果。

## 執行

```bash
# 模式一（預設）：並行生成 + 融合；不帶任務 = 內建示範 (Flutter + Riverpod + Logger)
python3 synthesizer.py
python3 synthesizer.py --mode synthesize "自訂任務"

# 模式二：Muse 產初稿，Qwen 審查修正
python3 synthesizer.py --mode critique "用 React + Zustand 實作待辦清單，含本地快取"

# 模式二反向：Qwen 產 UI 初稿，Muse 審查架構
python3 synthesizer.py --mode critique --reverse "用 Flutter 實作 TodoList 輸入框與清單畫面"

# 模式三：Qwen 拆解 JSON 規格，Muse 依規格實作（最終輸出 = 依規格的完整實作）
python3 synthesizer.py --mode pipeline "開發一個圖片上傳 App，含離線佇列與重試"
```

結果顯示於終端機，並存到 `outputs/`，檔名含模式與階段
（如 `*-critique-draft.md`、`*-critique-reverse-draft.md`、`*-pipeline-spec.md`、`*-final.md`）。

## Repo 內容

```
synthesizer.py        主程式（三種模式：synthesize / critique / pipeline）
config.example.toml   設定檔範本（不含任何預設端點）
requirements.txt      openai (async)
outputs/              執行產出（gitignore）
```

## 硬體提醒

兩個 27B–30B 模型以 4-bit 量化同時常駐約需 34–36GB 統一記憶體/VRAM。
不足時可把 `[qwen]` 與 `[muse]` 指向同一個伺服器、同一個模型，
僅靠不同 system prompt 區分角色（模式仍有效）；或改用「循序載入」
（先喚醒一個、結束釋放後再載入另一個），代價是換模型的載入時間。
