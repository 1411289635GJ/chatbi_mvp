"""Compatibility entry point for the ChatBI API."""

from chatbi.api_service import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_service:app", host="0.0.0.0", port=8000, reload=True)
