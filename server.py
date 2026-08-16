#!/usr/bin/env python3
"""
Multi-Agent Synthesizer — OpenAI 相容 API 伺服器
=================================================
把整個多模型協作流水線包成一個 LLM endpoint，讓任何支援 OpenAI API
的 agent / 客戶端直接載入：

    python3 server.py --port 8090

對 agent 來說就是一顆普通模型：
    base_url = http://localhost:8090/v1
    api_key  = 任意值
    model    = mas/synthesize | mas/critique | mas/critique-reverse | mas/pipeline

注意事項：
- 單次請求會跑完整條流水線，約需 15–17 分鐘，客戶端 timeout 要調大。
- 請求以 semaphore 序列化（底層模型伺服器一次只從容處理一條流水線），
  尖峰時段會排隊。
- stream=true 時每 30 秒送一個 SSE keepalive 註解行（標準客戶端會忽略），
  階段進度也以註解行送出，最終結果才進 content。
"""

import argparse
import asyncio
import json
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import synthesizer as mas

# 模型名稱 → (模式, 是否反向)
MODELS = {
    "mas/synthesize": ("synthesize", False),
    "mas/critique": ("critique", False),
    "mas/critique-reverse": ("critique", True),
    "mas/pipeline": ("pipeline", False),
}
# 也接受不帶前綴的名稱
for _name, _val in list(MODELS.items()):
    MODELS[_name.split("/", 1)[1]] = _val

app = FastAPI(title="Multi-Agent Synthesizer")
RUN_SEM = asyncio.Semaphore(1)  # 一次只跑一條流水線
_CFG = None


def get_cfg():
    global _CFG
    if _CFG is None:
        _CFG = mas.load_config()
    return _CFG


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatRequest(BaseModel):
    model: str = "mas/synthesize"
    messages: list[ChatMessage] = []
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


def _resolve_model(name: str):
    if name not in MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"未知模型 '{name}'。可用：{sorted(set(MODELS))}",
        )
    return MODELS[name]


def _extract_task(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user" and msg.content.strip():
            return msg.content.strip()
    raise HTTPException(status_code=400, detail="messages 中需要至少一則 user 訊息作為任務")


def _effective_cfg(req: ChatRequest) -> dict:
    cfg = get_cfg()
    if req.temperature is None and req.max_tokens is None:
        return cfg
    gen = dict(cfg["generation"])
    if req.temperature is not None:
        gen["temperature"] = req.temperature
    if req.max_tokens is not None:
        gen["max_tokens"] = req.max_tokens
    return {**cfg, "generation": gen}


async def _run_task(mode, reverse, task, cfg, queue=None):
    """序列化執行流水線；queue 存在時推送階段進度。回傳 (mode_label, final, stamp)。"""
    emit = (lambda msg: queue.put_nowait(("stage", msg))) if queue is not None else None
    async with RUN_SEM:
        mode_label, stages, final = await mas.run_mode(
            cfg, mode, task, reverse, emit=emit)
        stamp = mas.save_outputs(mode_label, task, stages, final)
    return mode_label, final, stamp


def _completion_obj(model_name: str, content: str) -> dict:
    return {
        "id": f"chatcmpl-mas-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/v1/models")
def list_models():
    names = [n for n in MODELS if n.startswith("mas/")]
    return {"object": "list", "data": [
        {"id": n, "object": "model", "created": 0,
         "owned_by": "multi-agent-synthesizer"}
        for n in names
    ]}


@app.get("/health")
def health():
    return {"status": "ok", "busy": RUN_SEM.locked()}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    mode, reverse = _resolve_model(req.model)
    task = _extract_task(req.messages)
    cfg = _effective_cfg(req)

    if not req.stream:
        _, final, _ = await _run_task(mode, reverse, task, cfg)
        return _completion_obj(req.model, final)

    queue: asyncio.Queue = asyncio.Queue()

    async def work():
        try:
            _, final, _ = await _run_task(mode, reverse, task, cfg, queue)
            await queue.put(("final", final))
        except Exception as e:  # 讓客戶端收到錯誤而非無限期等待
            await queue.put(("error", str(e)))

    asyncio.create_task(work())

    async def sse():
        base = {
            "id": f"chatcmpl-mas-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": req.model,
        }

        def chunk(delta, finish=None):
            payload = {**base, "choices": [
                {"index": 0, "delta": delta, "finish_reason": finish}]}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        yield chunk({"role": "assistant", "content": ""})
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"  # SSE 註解行，標準客戶端會忽略
                continue
            if kind == "stage":
                yield f": {payload}\n\n"
            elif kind == "final":
                yield chunk({"content": payload})
                yield chunk({}, finish="stop")
                yield "data: [DONE]\n\n"
                return
            else:  # error
                yield chunk({"content": f"[multi-agent-synthesizer] 執行失敗：{payload}"})
                yield chunk({}, finish="stop")
                yield "data: [DONE]\n\n"
                return

    return StreamingResponse(sse(), media_type="text/event-stream")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Agent Synthesizer API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    import uvicorn
    print(f"Multi-Agent Synthesizer endpoint: http://{args.host}:{args.port}/v1")
    print(f"可用模型: {', '.join(n for n in MODELS if n.startswith('mas/'))}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
