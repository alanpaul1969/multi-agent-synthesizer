#!/usr/bin/env python3
"""
Multi-Agent Synthesizer
=======================
並行呼叫兩個本地端模型（各司其職：UI 視覺 / 架構邏輯），
再將雙方產出交給第三個「融合節點」整合成最終成果。

使用方式：
  1. cp config.example.toml config.toml  並填入你的端點與模型名稱
  2. python3 synthesizer.py "你的任務描述"
     （或不帶參數，使用內建示範任務）

結果會顯示在終端機，並存到 outputs/ 目錄（含時間戳記）。
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

import tomllib
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.toml"

DEFAULT_TASK = (
    "請幫我實作一個 Flutter 元件，包含一個計數器按鈕，"
    "並且需要使用 Riverpod 進行狀態管理，"
    "同時在每次點擊時觸發 Local Data Logger 記錄操作日誌。"
)

SYNTHESIS_TEMPLATE = """我們正在開發同一個功能。以下是兩位工程師各自負責部分的草稿：

【前端視覺工程師 (著重 UI 結構) 的產出】：
{result_a}

【後端架構工程師 (著重狀態管理與 Logger 邏輯) 的產出】：
{result_b}

請你作為「首席架構師」，將兩份程式碼的優點完美結合。
要求：
1. 保留 UI 工程師優雅的畫面佈局。
2. 整合架構工程師嚴謹的狀態管理與 Logger 呼叫邏輯。
3. 輸出最終可以直接執行、無衝突的完整程式碼，並附上簡短的整合說明。
"""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(
            f"找不到 {CONFIG_PATH}\n"
            f"請先執行: cp {ROOT / 'config.example.toml'} {CONFIG_PATH}\n"
            f"並填入你自己的端點與模型設定。"
        )
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


async def fetch_llm_response(client, model_name, system_prompt, user_prompt,
                             role_name, temperature, max_tokens):
    print(f"[{role_name}] 思考與生成中...")
    start = time.time()
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        print(f"[{role_name}] 完成 ({time.time() - start:.1f}s, "
              f"{len(content)} chars)")
        return content
    except Exception as e:
        print(f"[{role_name}] 發生錯誤: {e}")
        return f"[{role_name}] 生成失敗: {e}"


async def main():
    cfg = load_config()
    task_prompt = " ".join(sys.argv[1:]).strip() or DEFAULT_TASK

    gen = cfg["generation"]
    temperature, max_tokens = gen["temperature"], gen["max_tokens"]

    def make_client(section):
        return AsyncOpenAI(base_url=section["base_url"], api_key=section["api_key"])

    client_a, client_b, client_s = (make_client(cfg[k]) for k in ("qwen", "muse", "synthesizer"))

    start_time = time.time()
    print(f"=== 任務 ===\n{task_prompt}\n")

    # --- 第一階段：並行分發 ---
    print("=== 第一階段：並行讓兩款模型各自發揮專長 ===")
    result_a, result_b = await asyncio.gather(
        fetch_llm_response(client_a, cfg["qwen"]["model"],
                           cfg["qwen"]["system_prompt"], task_prompt,
                           "Qwen-UI設計師", temperature, max_tokens),
        fetch_llm_response(client_b, cfg["muse"]["model"],
                           cfg["muse"]["system_prompt"], task_prompt,
                           "Muse-架構工程師", temperature, max_tokens),
    )

    # --- 第二階段：融合 ---
    print("\n=== 第二階段：融合大腦 (Synthesizer) ===")
    final_result = await fetch_llm_response(
        client_s, cfg["synthesizer"]["model"],
        cfg["synthesizer"]["system_prompt"],
        SYNTHESIS_TEMPLATE.format(result_a=result_a, result_b=result_b),
        "Muse-首席架構師 (融合節點)", temperature, max_tokens,
    )

    elapsed = time.time() - start_time
    print(f"\n總共花費時間: {elapsed:.1f} 秒")
    print("\n=== 最終融合結果 ===\n")
    print(final_result)

    # --- 存檔 ---
    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out_dir / f"{stamp}-task.txt").write_text(task_prompt, encoding="utf-8")
    (out_dir / f"{stamp}-qwen.md").write_text(result_a, encoding="utf-8")
    (out_dir / f"{stamp}-muse.md").write_text(result_b, encoding="utf-8")
    (out_dir / f"{stamp}-final.md").write_text(final_result, encoding="utf-8")
    print(f"\n已存檔至 outputs/{stamp}-*.md")


if __name__ == "__main__":
    asyncio.run(main())
