# Multi-Agent Synthesizer

讓兩個本地端 LLM 並行分工（UI 視覺 / 架構邏輯），再交給第三個「融合節點」
整合成一份可直接使用的最終成果。適用於任何 OpenAI API 相容的本地伺服器
（llama.cpp、LM Studio、vLLM、Ollama…）。

## 架構

```
                ┌──> 模型 A (UI / 視覺專家) ──┐
任務 prompt ────┤                            ├──> 融合節點 (首席架構師) ──> 最終成果
                └──> 模型 B (架構 / 狀態專家)─┘
                     (asyncio.gather 並行)
```

- **角色注入 (Role Prompting)**：透過 system prompt 限制各模型視野，
  逼出單一領域的深度，減少幻覺。
- **並行呼叫**：兩個生成任務同時進行，第一階段只需等最慢的那一個。
- **融合**：將雙方草稿組成比較式 prompt，交給推理能力最強的模型整合。

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
# 不帶參數 = 內建示範任務 (Flutter + Riverpod + Logger 計數器)
python3 synthesizer.py

# 自訂任務
python3 synthesizer.py "用 React + Zustand 實作一個待辦清單，含本地快取"
```

結果顯示於終端機，並存到 `outputs/`（task / qwen / muse / final 各一份）。

## Repo 內容

```
synthesizer.py        主程式（並行分發 + 融合）
config.example.toml   設定檔範本（不含任何預設端點）
requirements.txt      openai (async)
outputs/              執行產出（gitignore）
```
