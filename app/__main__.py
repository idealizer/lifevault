import uvicorn

from app.config import host, port

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=host(), port=port(), reload=False)
