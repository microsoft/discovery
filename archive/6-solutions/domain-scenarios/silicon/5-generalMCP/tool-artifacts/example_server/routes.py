from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi import APIRouter
from app import app

# Create a router with a general tag for API documentation organization
router = APIRouter(tags=["General"])


@router.get("/")
async def homepage():
    """Root endpoint that returns a simple HTML welcome page"""
    html_content = (
        "<h1>FastAPI MCP SSE</h1>"
        "<p>Welcome to the SSE demo with MCP integration.</p>"
    )
    return HTMLResponse(html_content)


@router.get("/about")
async def about():
    """About endpoint that returns information about the application"""
    return PlainTextResponse(
        "About FastAPI MCP SSE: A demonstration of Server-Sent Events "
        "with Model Context Protocol integration."
    )


@router.get("/status")
async def status():
    """Status endpoint that returns the current server status"""
    status_info = {
        "status": "running",
        "server": "FastAPI MCP SSE",
        "version": "0.1.0",
    }
    return JSONResponse(status_info)


# Include the router in the main application
app.include_router(router)
