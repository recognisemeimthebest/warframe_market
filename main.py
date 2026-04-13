import uvicorn

from src.config import WEB_HOST, WEB_PORT, setup_logging
from src.web.app import app
from src.web.routes import router

app.include_router(router)

if __name__ == "__main__":
    setup_logging()
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)
