#!/usr/bin/env python3
"""
Runner script for the bin discovery agent.

This shows how to invoke the Claude Agent SDK agent to discover a council's bin API.
"""

import asyncio
import sys
import os
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions
from bin_discovery_agent import bin_discovery_agent


async def discover_council(council_name: str, url: str, postcode: str):
    """
    Run the discovery agent for a single council.

    Args:
        council_name: Name of the council
        url: Council website URL
        postcode: Test postcode for that council
    """
    # Set working directory to src/agents so paths work
    os.chdir(Path(__file__).parent)

    # Create output directories
    (Path.cwd().parent.parent / "data" / "discoveries").mkdir(
        exist_ok=True, parents=True
    )
    (Path.cwd().parent.parent / "configs").mkdir(exist_ok=True, parents=True)

    # Build the user prompt with council details
    user_prompt = f"""Discover the bin collection API for {council_name}.

Council URL: {url}
Test Postcode: {postcode}

Please:
1. Navigate to the bin lookup page
2. Fill in the postcode form
3. Capture all network traffic
4. Identify the bin collection API
5. Generate a YAML config file

Save the network log as: ../../data/discoveries/{council_name.lower().replace(" ", "_")}_network.json
Save the config as: ../../configs/{council_name.lower().replace(" ", "_")}.yaml
"""

    print(f"\n{'=' * 60}")
    print(f"Starting discovery for: {council_name}")
    print(f"{'=' * 60}\n")

    # Create options with the agent registered
    options = ClaudeAgentOptions(agents={"bin_discovery": bin_discovery_agent})

    # Run the agent - query() is async
    async for message in query(prompt=user_prompt, options=options):
        print(str(message))

    print(f"\n{'=' * 60}")
    print("Discovery complete!")
    print(f"{'=' * 60}\n")


async def main():
    """
    Usage:
        # Single council
        python run_discovery.py "Stirling Council" "https://my.stirling.gov.uk/" "FK15 0AF"

        # From CSV (future enhancement)
        python run_discovery.py --batch
    """

    if len(sys.argv) < 4:
        print("Usage: python run_discovery.py <council-name> <url> <postcode>")
        print("\nExample:")
        print(
            '  python run_discovery.py "Stirling Council" "https://my.stirling.gov.uk/" "FK15 0AF"'
        )
        sys.exit(1)

    council_name = sys.argv[1]
    url = sys.argv[2]
    postcode = sys.argv[3]

    await discover_council(council_name, url, postcode)


if __name__ == "__main__":
    asyncio.run(main())
