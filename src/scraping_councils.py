from prompts import PROMPT
import asyncio
import polars as pl
from pydantic_agent import create_agent, TRACE_DIR
import re
from pydantic_ai.usage import UsageLimits
import json


async def run_agent(
    council_name,
    prompt,
    model_id="gemini-2.5-flash",
):
    agent = create_agent(council_name, model_id=model_id)

    # Start MCP servers and run the agent
    async with agent.run_mcp_servers():
        result = await agent.run(prompt, usage_limits=UsageLimits(request_limit=20))
        print(result.output)
        print(result.usage)
        return result


async def main(prompt="""Go to example.com"""):
    councils = pl.read_csv("data/bins_info_with_uprn.csv").to_dicts()

    for council in councils:
        if not council.get("uprn_url"):
            prompt = PROMPT.format(
                URL=council.get("URL"),
                POSTCODE1=council.get("pcd1"),
                POSTCODE2=council.get("pcd2"),
            )
            council_name = council.get("Authority Name").replace(" ", "_").lower()

            try:
                result = await run_agent(
                    council_name=council_name,
                    prompt=prompt,
                    model_id="gemini-2.5-flash",
                )

                result_dict = {
                    "output": result.output.model_dump(),
                    "usage": result.usage,  # Already a dict
                }

                # Write to JSON file
                with open(
                    f"{TRACE_DIR.format(council_name=council_name)}_result.json",
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(result_dict, f, indent=2, ensure_ascii=False)

            except Exception as e:
                print(f"This run failed with exception {e}")


if __name__ == "__main__":
    asyncio.run(main())
