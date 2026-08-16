# Multi-Agent Synthesizer

> 雙本地 LLM 協作框架：讓兩顆本地模型分工合作、互審產出，並可包成一個 OpenAI 相容 endpoint 給任何 agent 直接載入。
>
> A dual local-LLM collaboration framework: two local models divide work, review each other's output, and the whole pipeline can be served as a single OpenAI-compatible endpoint for any agent to load.

**[中文說明](#中文說明)** | **[English](#english)**

適用於任何 OpenAI API 相容的本地伺服器（llama.cpp、LM Studio、vLLM、Ollama…）。
Works with any OpenAI API-compatible local server (llama.cpp, LM Studio, vLLM, Ollama…).

---

# 中文說明

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

區段名稱只是代號，任何兩顆模型都能套用。模型名稱可用
`curl http://<host>:<port>/v1/models` 查詢。

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

## 當作 LLM endpoint 給 agent 用（server 模式）

把整條流水線包成一個 OpenAI 相容端點，任何支援 OpenAI API 的
agent／客戶端都能直接載入：

```bash
python3 server.py --port 8090
```

| 設定 | 值 |
|---|---|
| base_url | `http://localhost:8090/v1` |
| api_key | 任意值（如 `local`） |
| model | `mas/synthesize`、`mas/critique`、`mas/critique-reverse`、`mas/pipeline` |

模式就是「模型名稱」：agent 要哪種協作模式，就選對應的 model。
最後一則 user 訊息即為任務 prompt；請求可覆寫 `temperature` / `max_tokens`
（不給則用 config.toml 的 `[generation]`）。

注意事項：

- 單次請求跑完整條流水線，約 **15–17 分鐘**，客戶端 timeout 要調大。
- 請求序列化執行（底層模型一次只從容處理一條流水線），排隊中可用
  `GET /health` 看 `busy` 狀態。
- `stream=true` 時每 30 秒送 SSE keepalive（註解行，標準客戶端會忽略），
  階段進度也以註解行推送，最終結果才進 content。

## Repo 內容

```
synthesizer.py        主程式（三種模式：synthesize / critique / pipeline）
server.py             OpenAI 相容 API 伺服器（把流水線包成 LLM endpoint）
config.example.toml   設定檔範本（不含任何預設端點）
requirements.txt      openai (async)、fastapi、uvicorn
outputs/              執行產出（gitignore）
```

## 硬體提醒

兩個 27B–30B 模型以 4-bit 量化同時常駐約需 34–36GB 統一記憶體/VRAM。
不足時可把 `[qwen]` 與 `[muse]` 指向同一個伺服器、同一個模型，
僅靠不同 system prompt 區分角色（模式仍有效）；或改用「循序載入」
（先喚醒一個、結束釋放後再載入另一個），代價是換模型的載入時間。

---

# English

## Three Collaboration Modes

### Mode 1 `synthesize`: Parallel Generation + Fusion Brain (default)

```
                 ┌──> Model A (UI / visual expert) ─────┐
task prompt ─────┤                                       ├──> Fusion node (chief architect) ──> final result
                 └──> Model B (architecture / state) ────┘
                      (asyncio.gather, parallel)
```

Both models answer the same task in parallel (you only wait for the slower one),
then a third node fuses the strengths of both outputs.

### Mode 2 `critique`: Critic & Refine

```
task ──> Model B drafts the architecture ──> Model A reviews from a UI/UX perspective,
                                             catches gaps, and outputs the corrected version
```

A developer–reviewer relationship: no third generation step — the reviewer
directly outputs the integrated, corrected version.

Add `--reverse` to flip the direction: Model A drafts the UI first, Model B reviews
the architecture and state management. Running both directions gives you a full
"double-blind review".

### Mode 3 `pipeline`: Specialized Pipeline

```
task ──> Model A decomposes it into a structured JSON spec ──> Model B implements
         (widget tree, states, events, data flow)              state management & logic ──> final result
```

The two models never do the same job: A handles requirement/UI analysis,
B handles core logic implementation. The final output is a single artifact:
B's complete, runnable implementation of the spec (`*-final.md`); the JSON spec
itself is also saved (`*-spec.md`) as an inspectable/reusable intermediate.

## Installation

```bash
pip install -r requirements.txt
cp config.example.toml config.toml   # fill in YOUR OWN endpoints and model names
```

## Configuration

`config.toml` (gitignored, never committed) has four sections:

| Section | Purpose |
|---|---|
| `[qwen]` | Model A — UI / visual expert: endpoint, model name, system prompt |
| `[muse]` | Model B — architecture / state-management expert |
| `[synthesizer]` | Fusion node (use your strongest-reasoning model here) |
| `[generation]` | temperature / max_tokens |

Section names are just labels — any two models will do. Look up model names with
`curl http://<host>:<port>/v1/models`.

**Not enough VRAM for two models?** Point `[qwen]` and `[muse]` at the same
server and the same model, and separate the roles purely via different
system_prompts — you still get the "collision of perspectives → fusion" effect.

## Usage

```bash
# Mode 1 (default): parallel generation + fusion; no task = built-in demo (Flutter + Riverpod + Logger)
python3 synthesizer.py
python3 synthesizer.py --mode synthesize "your task"

# Mode 2: Muse drafts, Qwen reviews & fixes
python3 synthesizer.py --mode critique "Build a todo list with React + Zustand, with local caching"

# Mode 2 reversed: Qwen drafts the UI, Muse reviews the architecture
python3 synthesizer.py --mode critique --reverse "Build a TodoList input + list screen in Flutter"

# Mode 3: Qwen produces a JSON spec, Muse implements it (final output = full implementation)
python3 synthesizer.py --mode pipeline "Build an image-upload app with an offline queue and retries"
```

Results print to the terminal and are saved under `outputs/` with mode and stage
in the filename (e.g. `*-critique-draft.md`, `*-critique-reverse-draft.md`,
`*-pipeline-spec.md`, `*-final.md`).

## As an LLM Endpoint for Agents (Server Mode)

Wrap the whole pipeline as an OpenAI-compatible endpoint that any
OpenAI-API-capable agent or client can load directly:

```bash
python3 server.py --port 8090
```

| Setting | Value |
|---|---|
| base_url | `http://localhost:8090/v1` |
| api_key | anything (e.g. `local`) |
| model | `mas/synthesize`, `mas/critique`, `mas/critique-reverse`, `mas/pipeline` |

The mode **is** the model name: the agent picks which collaboration mode it wants
by choosing the corresponding model. The last user message becomes the task
prompt; requests may override `temperature` / `max_tokens` (defaults come from
`[generation]` in config.toml).

Notes:

- A single request runs the full pipeline, roughly **15–17 minutes** — raise
  your client's timeout accordingly.
- Requests are serialized (the backing model servers can only comfortably handle
  one pipeline at a time); check `GET /health` for the `busy` state.
- With `stream=true`, an SSE keepalive comment is sent every 30 seconds (standard
  clients ignore comment lines), stage progress is pushed as comment lines, and
  only the final result goes into the content.

## Repo Contents

```
synthesizer.py        Main program (three modes: synthesize / critique / pipeline)
server.py             OpenAI-compatible API server (the pipeline as one LLM endpoint)
config.example.toml   Config template (ships with no default endpoints)
requirements.txt      openai (async), fastapi, uvicorn
outputs/              Run artifacts (gitignored)
```

## Hardware Note

Running two 27B–30B models at 4-bit quantization simultaneously needs roughly
34–36GB of unified memory/VRAM. If you have less, either point `[qwen]` and
`[muse]` at the same server and same model (roles separated purely by system
prompts — the modes still work), or load the models sequentially (wake one,
release it, then load the other) at the cost of model-loading time.
