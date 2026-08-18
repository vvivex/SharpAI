import json
import os
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(title="SharpAI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("SHARPAI_MODEL", "qwen3:4b")

SYSTEM_PROMPT = """
You are SharpAI, a general-purpose conversational AI.

Have natural conversations with the user. The user is free to discuss
whatever topics they want. Do not require specific keywords, commands,
phrases, or predefined categories before answering.

Be useful, conversational, accurate, and honest. Explain things clearly.
Maintain context from the conversation supplied by the client.

Do not claim to have capabilities you do not have. If you are unsure,
say so. Follow the model's normal safety behavior where applicable.
"""

@app.get("/health")
def health():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.ok:
            models = r.json().get("models", [])
            installed = any(m.get("name") == MODEL for m in models)
            return {
                "online": True,
                "ollama": True,
                "model": MODEL,
                "model_installed": installed
            }
    except requests.RequestException:
        pass

    return {
        "online": True,
        "ollama": False,
        "model": MODEL,
        "model_installed": False
    }


@app.post("/chat")
def chat(payload: dict):
    messages = payload.get("messages", [])
    stream = bool(payload.get("stream", True))

    if not isinstance(messages, list):
        return {"error": "messages must be a list"}

    ollama_messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    for message in messages:
        role = message.get("role")
        content = message.get("content")

        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue

        ollama_messages.append({
            "role": role,
            "content": content
        })

    if not ollama_messages or len(ollama_messages) == 1:
        return {"error": "No user message was provided."}

    request_body = {
        "model": MODEL,
        "messages": ollama_messages,
        "stream": stream,
        "options": {
            "temperature": 0.7
        }
    }

    if not stream:
        try:
            r = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json=request_body,
                timeout=300
            )
            r.raise_for_status()
            data = r.json()
            return {
                "response": data.get("message", {}).get("content", "")
            }
        except requests.RequestException as exc:
            return {"error": f"Ollama connection failed: {exc}"}

    def generate():
        try:
            with requests.post(
                f"{OLLAMA_URL}/api/chat",
                json=request_body,
                stream=True,
                timeout=300
            ) as r:
                r.raise_for_status()

                for raw_line in r.iter_lines():
                    if not raw_line:
                        continue

                    data = json.loads(raw_line)
                    token = data.get("message", {}).get("content", "")

                    if token:
                        yield json.dumps(
                            {"token": token}
                        ) + "\n"

                    if data.get("done"):
                        yield json.dumps(
                            {"done": True}
                        ) + "\n"
                        break

        except Exception as exc:
            yield json.dumps({
                "error": f"Ollama error: {exc}"
            }) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson"
    )


@app.get("/")
def root():
    return {
        "name": "SharpAI API",
        "status": "running",
        "model": MODEL
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
