PROMPT = """
### Bin Collection Schedule Lookup Task

## Objective

Research and retrieve bin collection information for a specific council area by accessing their official website and lookup system.

## Instructions

# Step 1: Navigate to Council Website
Access the council website at: {URL}

# Step 2: Test Postcodes
Search for the collection schedules for this postcodes: {POSTCODE1}
If a full address is required, use any house number (e.g., "1 [Street Name]") or select any option on a dropdown. The specific address doesn't matter - we only need the collection schedule format

## Output

Provide the following information for each bin type (if exists) + the postcode:
    next_pickup_day
    frequency 
    bin_colour

If it doesn't exist, that is ok. Just answer None for these fields.

## Troubleshooting
If you encounter issues:

Look for alternative entry points (e.g., "Check my bin day")
Note any technical difficulties in your response
If the provided postcode doesn't work try postcodes from the same council area (use your knowledge of local postcodes). Here is a suggestion {POSTCODE2}
"""
