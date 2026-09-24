import azure.functions as func

from workday_mcp.mcp_server import build_mcp_app

asgi_app = build_mcp_app()

app = func.AsgiFunctionApp(app=asgi_app, http_auth_level=func.AuthLevel.FUNCTION)
