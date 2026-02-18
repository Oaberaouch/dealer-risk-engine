from fastapi import FastAPI

app = FastAPI(title="Dealer Risk Engine", version="0.0.1")

@app.get("/health")
def health():
    return {"status": "ok", "service": "dealer-risk-engine"}