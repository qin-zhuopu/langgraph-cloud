#!/usr/bin/env python3
"""LangGraph Cloud server startup script.

Run this script to start the FastAPI server with auto-reload enabled.
"""

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
