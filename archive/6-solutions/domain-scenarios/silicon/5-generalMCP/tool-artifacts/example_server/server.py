import uvicorn
import os
from app import app

# Environment variable configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "80"))


def run():
    """Start the FastAPI server with uvicorn"""
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    run()
