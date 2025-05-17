from fastapi import FastAPI
from .routes import strategies, brokers, positions, trades
import uvicorn
from .config import API_PORT

app = FastAPI()

# Include routers
app.include_router(strategies.router, prefix="/strategies", tags=["Strategies"])
app.include_router(brokers.router, prefix="/brokers", tags=["Brokers"])
app.include_router(positions.router, prefix="/positions", tags=["Positions"])
app.include_router(trades.router, prefix="/trades", tags=["Trades"])

@app.get("/")
def root():
    return {"status": "ok", "message": "AlgoSat Trading API"}

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=API_PORT, reload=True)
