#!/usr/bin/env python3
"""
Multi-Agent Synthesizer
=======================
雙本地模型協作框架，三種模式可選：

  synthesize  並行生成 + 融合大腦：兩模型同時作答，第三節點融合優點（預設）
  critique    互相審查：模型 B 產初稿，模型 A 以 UI/介面視角審查並輸出修正版
  pipeline    專長分工：模型 A 先產出結構化 JSON 規格，模型 B 依規格實作邏輯

使用方式：
  1. cp config.example.toml config.toml  並填入你的端點與模型名稱
  2. python3 synthesizer.py --mode synthesize "你的任務描述"
     （或不帶參數，使用內建示範任務）

結果會顯示在終端機，並存到 outputs/ 目錄（含時間戳記）。
"""

import argparse
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

# --- 模式二：Critic & Refine（模型 B 產初稿，模型 A 審查修正） ---
CRITIQUE_DRAFT_SYSTEM = (
    "你是一個專精於架構與資料流的資深工程師。"
    "請產出完整可執行的第一版實作，著重狀態管理、解耦架構與資料記錄的穩健性。"
)
CRITIQUE_REVIEW_TEMPLATE = """你是一位專精 UI/UX 與前端介面的審查工程師。
以下是架構工程師針對此任務產出的初稿：

【任務】
{task}

【初稿】
{draft}

請你發揮介面與使用者經驗的專業，審查這份程式碼：
1. 指出哪些變數/狀態沒有對應到畫面元件，哪些操作會造成畫面卡頓或回饋不明確。
2. 直接輸出修正後的完整整合版本（可直接執行、無衝突），並附上簡短的審查與修正說明。
"""

# --- 模式三：Specialized Pipeline（模型 A 產 JSON 規格，模型 B 實作） ---
PIPELINE_SPEC_SYSTEM = (
    "你是一位需求分析與介面設計師。請將任務描述拆解成結構化的 JSON 規格，"
    "包含畫面元件樹、每個元件的狀態與事件、以及資料流需求。"
    "只輸出 JSON（可包在 ```json 區塊中），不要輸出其他說明文字。"
)
PIPELINE_IMPL_TEMPLATE = """你是一位專精架構與資料流的資深工程師。
以下是介面設計師針對此任務產出的結構化 JSON 規格：

【任務】
{task}

【JSON 規格】
{spec}

請依據這份規格實作：
1. 完整的狀態管理與資料流邏輯（例如 Provider / Notifier / Repository 分層）。
2. 將規格中每個元件與事件串接到對應的狀態與副作用（含資料記錄 Logger）。
3. 輸出完整可直接執行的程式碼，並附上簡短的實作說明。
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


async def run_synthesize(cfg, task_prompt):
    """模式一：並行生成 + 融合大腦。回傳 (階段產出 dict, 最終結果)。"""
    gen = cfg["generation"]
    client_a, client_b, client_s = _clients(cfg)

    print("=== 第一階段：並行讓兩款模型各自發揮專長 ===")
    result_a, result_b = await asyncio.gather(
        _call(client_a, cfg["qwen"], task_prompt, "Qwen-UI設計師", gen),
        _call(client_b, cfg["muse"], task_prompt, "Muse-架構工程師", gen),
    )

    print("\n=== 第二階段：融合大腦 (Synthesizer) ===")
    final = await _call(
        client_s, cfg["synthesizer"],
        SYNTHESIS_TEMPLATE.format(result_a=result_a, result_b=result_b),
        "首席架構師 (融合節點)", gen,
        system_override=cfg["synthesizer"]["system_prompt"],
    )
    return {"qwen": result_a, "muse": result_b}, final


async def run_critique(cfg, task_prompt):
    """模式二：互相審查 (Critic & Refine)。模型 B 產初稿，模型 A 審查修正。"""
    gen = cfg["generation"]
    client_a, client_b, _ = _clients(cfg)

    print("=== 第一步：Muse 產出架構初稿 ===")
    draft = await _call(client_b, cfg["muse"], task_prompt,
                        "Muse-開發工程師", gen,
                        system_override=CRITIQUE_DRAFT_SYSTEM)

    print("\n=== 第二步：Qwen 以 UI/介面視角審查並修正 ===")
    final = await _call(
        client_a, cfg["qwen"],
        CRITIQUE_REVIEW_TEMPLATE.format(task=task_prompt, draft=draft),
        "Qwen-審查工程師", gen,
        system_override=cfg["qwen"]["system_prompt"],
    )
    return {"draft": draft}, final


async def run_pipeline(cfg, task_prompt):
    """模式三：專長分工。模型 A 產 JSON 規格，模型 B 依規格實作。"""
    gen = cfg["generation"]
    client_a, client_b, _ = _clients(cfg)

    print("=== 第一步：Qwen 拆解任務為結構化 JSON 規格 ===")
    spec = await _call(client_a, cfg["qwen"], task_prompt,
                       "Qwen-需求/介面分析師", gen,
                       system_override=PIPELINE_SPEC_SYSTEM)

    print("\n=== 第二步：Muse 依規格實作核心邏輯 ===")
    final = await _call(
        client_b, cfg["muse"],
        PIPELINE_IMPL_TEMPLATE.format(task=task_prompt, spec=spec),
        "Muse-實作工程師", gen,
        system_override=cfg["muse"]["system_prompt"],
    )
    return {"spec": spec}, final


MODES = {
    "synthesize": (run_synthesize, "並行生成 + 融合大腦"),
    "critique": (run_critique, "互相審查 (開發者 vs 審查者)"),
    "pipeline": (run_pipeline, "專長分工 (規格 → 實作)"),
}


def _clients(cfg):
    def make(section):
        return AsyncOpenAI(base_url=section["base_url"], api_key=section["api_key"])
    return (make(cfg[k]) for k in ("qwen", "muse", "synthesizer"))


async def _call(client, section, user_prompt, role_name, gen, system_override=None):
    return await fetch_llm_response(
        client, section["model"],
        system_override or section["system_prompt"],
        user_prompt, role_name, gen["temperature"], gen["max_tokens"],
    )


async def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Synthesizer")
    parser.add_argument("--mode", choices=sorted(MODES), default="synthesize",
                        help="協作模式（預設 synthesize）")
    parser.add_argument("task", nargs="*", help="任務描述（省略則用內建示範任務）")
    args = parser.parse_args()

    cfg = load_config()
    task_prompt = " ".join(args.task).strip() or DEFAULT_TASK
    runner, mode_desc = MODES[args.mode]

    print(f"=== 模式: {args.mode}（{mode_desc}） ===")
    print(f"=== 任務 ===\n{task_prompt}\n")

    start_time = time.time()
    stages, final_result = await runner(cfg, task_prompt)

    elapsed = time.time() - start_time
    print(f"\n總共花費時間: {elapsed:.1f} 秒")
    print("\n=== 最終結果 ===\n")
    print(final_result)

    # --- 存檔 ---
    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    files = {"task": task_prompt, "final": final_result}
    files.update(stages)
    for name, content in files.items():
        (out_dir / f"{stamp}-{args.mode}-{name}.md").write_text(
            content, encoding="utf-8")
    print(f"\n已存檔至 outputs/{stamp}-{args.mode}-*.md")


if __name__ == "__main__":
    asyncio.run(main())
