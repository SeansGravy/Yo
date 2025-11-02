from fastapi import FastAPI, Body
import requests, os

app = FastAPI(title="Yo API")

@app.post("/chat")
def chat(query: str = Body(..., embed=True)):
    r = requests.post("http://ollama:11434/api/generate",
                      json={"model": "llama3", "prompt": query})
    return {"response": r.text}
