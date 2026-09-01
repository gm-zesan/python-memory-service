import uvicorn
from app.main import app
from app.config import config

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)
