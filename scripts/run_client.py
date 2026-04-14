#!/usr/bin/env python3
"""LangGraph Cloud CLI client startup script.

Run this script to start the interactive CLI client.

Usage:
    python -m scripts.run_client              # WebSocket mode
    python -m scripts.run_client --poll       # Polling mode
    python -m scripts.run_client --user=abc   # Custom user ID
"""

if __name__ == "__main__":
    from app.client_sdk.cli import main
    import asyncio

    asyncio.run(main())
