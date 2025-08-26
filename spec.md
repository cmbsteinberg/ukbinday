# UK Council Bin Collection Scraper - Specification

## Overview

A generalised scraper for extracting bin collection information from UK council websites using pure API calls. Based on analysis of Playwright traces from 100+ council websites.

## Problem Analysis

### Data Source
- Analyzed traces from `data/traces/*/trace.json` and `reduced_results.json`
- All council websites ultimately use API endpoints for data retrieval
- Playwright traces were used to discover these endpoints, not to replicate browser workflows

### Key Findings
All councils follow similar patterns but implement them differently:
1. Postcode search to find addresses
2. Address selection to get bin collection details
3. Return standardized data: `{postcode, general_waste, recycling, food_waste, garden_waste}`

## Architecture Design

### Core Principle
**Single responsibility classes with YAML-driven configuration**

- `BinCollectionScraper`: Pure API extraction, returns raw responses
- `DataNormalizer`: Handles format standardization (separate class)
- `CouncilRouter`: Maps postcodes to councils (separate class)
- YAML configs: Define API patterns per council

### API Patterns Identified

Through trace analysis, identified 4 distinct API patterns:

#### 1. REST APIs (Cambridge pattern)
```
GET https://servicelayer3c.azure-api.net/wastecalendar/address/search?postcode=CB11BB
GET https://servicelayer3c.azure-api.net/wastecalendar/collection/search/200004167511/?authority=CCC&numberOfCollections=12
```

#### 2. POST Services (Brighton pattern)
```
GET https://enviroservices.brighton-hove.gov.uk/metamodel.json  # Schema
POST https://enviroservices.brighton-hove.gov.uk/xas/           # Data
```

#### 3. Token-based APIs (Croydon pattern)
```
GET landing_page → extract webpage_token
POST endpoint_with_token
```

#### 4. Form-token APIs (Wigan pattern)
```
GET form_page → extract ViewState/EVENTVALIDATION tokens
POST with form tokens + postcode
```

## Implementation Requirements

### Error Handling
- **404 errors**: Clear warning when endpoints not found
- **403 errors**: Authentication/token issues
- **Connection errors**: Network failures
- **Data validation**: Invalid JSON responses

### Design Constraints
- **No rate limiting**: Not required at this stage
- **No caching**: Will be handled separately
- **No data validation**: Raw API responses returned
- **Single method per council**: No fallback strategies
- **No token persistence**: Fresh tokens for each request

### Configuration-Driven
- Each council defined in YAML configuration
- New councils added without code changes
- API patterns abstracted into 4 core methods

## Expected Output

### Files to Implement
1. `bin_scraper.py` - Main scraper class
2. `council_bin_config.yaml` - Council configurations
3. `spec.md` - This specification document

### Data Flow
```
Input: (council_name, postcode)
↓
Load council config from YAML
↓
Determine API pattern type
↓
Execute appropriate API method
↓
Return raw API response
```

### Example Usage
```python
scraper = BinCollectionScraper('council_bin_config.yaml')
raw_data = scraper.get_collections('cambridge_city_council', 'CB1 1BB')
# Returns raw API response for normalization by separate class
```

## Success Criteria

- Single `BinCollectionScraper` class handles all councils
- 4 methods cover all API patterns identified in traces
- YAML configuration drives behavior
- Clear error messages for API failures
- Raw API responses returned without transformation
- Minimal dependencies (requests + yaml)