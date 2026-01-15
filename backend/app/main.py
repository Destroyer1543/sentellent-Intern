from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Sentellent Agentic Assistant")

class ChatRequest(BaseModel):
    user_id: str
    message: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat")
def chat(req: ChatRequest):
    # TODO: replace with LangGraph agent call
    return {"reply": f"Echo: {req.message}", "user_id": req.user_id}