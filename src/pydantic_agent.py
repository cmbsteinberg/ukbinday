from dotenv import load_dotenv

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.mcp import MCPServerStdio, MCPServerHTTP
from pydantic_ai.settings import ModelSettings

from mcp.server.fastmcp import FastMCP
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from models import BinDays

# Loads GOOGLE_APPLICATION_CREDENTIALS
load_dotenv()

TRACE_DIR = "./data/traces/{council_name}"


def create_agent(
    council_name,
    model_id="gemini-2.5-flash",
    system_prompt: str = "You are a helpful web-browsing agent who researches and retrieves bin collection information for a specific council area by accessing their official website and lookup system",
):
    # Create MCP server for Playwright
    playwright_server = MCPServerStdio(
        command="npx",
        args=[
            "@playwright/mcp@latest",
            "--headless",
            "--save-trace",
            f"--output-dir={TRACE_DIR.format(council_name=council_name)}",
        ],
    )

    provider = GoogleProvider(
        location="global",
        vertexai=True,
    )

    model = GoogleModel(
        model_id,
        provider=provider,
    )

    # Create agent with Vertex AI model and Playwright MCP server
    agent = Agent(
        model,  # Using Vertex AI Gemini model
        mcp_servers=[playwright_server],
        output_type=BinDays,
        system_prompt=system_prompt,
        model_settings=ModelSettings(temperature=0.3),
    )

    return agent
