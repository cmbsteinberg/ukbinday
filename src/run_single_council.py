# run_single_council.py

import asyncio
import json
import argparse
from pydantic_agent import create_agent
from pydantic_ai.usage import UsageLimits
from prompts import PROMPT  # Assuming PROMPT is in a prompts.py file


async def run_agent(
    prompt,
    output_dir,
    model_id="gemini-2.5-flash",
):
    """Runs the agent for a single council."""

    agent = create_agent(
        output_dir=output_dir,
        model_id=model_id,
    )

    # Start MCP servers and run the agent
    async with agent.run_mcp_servers():
        result = await agent.run(
            prompt,
            usage_limits=UsageLimits(request_limit=20),
        )
        return result


async def main():
    """Parses arguments and executes the agent run."""
    parser = argparse.ArgumentParser(description="Run agent for a single council.")
    parser.add_argument(
        "--output-dir", required=True, help="Name of the council authority."
    )
    parser.add_argument("--url", required=True, help="URL for the council.")
    parser.add_argument("--postcode", required=True, help="Postcode for the council.")
    args = parser.parse_args()

    # Sanitize council name for directory path
    prompt = PROMPT.format(
        URL=args.url,
        POSTCODE1=args.postcode,
    )
    try:
        result = await run_agent(
            output_dir=args.output_dir,
            prompt=prompt,
            model_id="gemini-2.5-flash",
        )
        print(f"--- Output for {args.output_dir} ---")
        print(result.output)
        print(result.usage())

        result_dict_parsed = {
            "output": json.loads(result.output.model_dump_json()),
            "messages": json.loads(result.all_messages_json()),
        }

        # Define the full path for the output file
        output_path = f"{args.output_dir}/result.json"

        # Write to JSON file
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result_dict_parsed, f, indent=2, ensure_ascii=False)

        print(f"✅ File saved to {output_path}")

    except Exception as e:
        print(f"❌ Run for {args.output_dir} failed with exception: {e}")


if __name__ == "__main__":
    asyncio.run(main())
