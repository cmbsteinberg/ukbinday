# Council Data Patterns Analysis

This document summarizes the key patterns discovered across 306 UK councils' bin collection data structures.

## Overview Statistics

- **Total councils**: 306
- **Response formats**: JSON (101), HTML (197), XML (7)
- **Request types**: single_api (185), id_lookup_then_api (79), token_then_api (42)

## Response Format Patterns

### Distribution by Request Type

| Request Type | JSON | HTML | XML |
|--------------|------|------|-----|
| `token_then_api` | 78.6% | 21.4% | 0% |
| `id_lookup_then_api` | 16.5% | 82.3% | 1.3% |
| `single_api` | 29.7% | 66.5% | 3.8% |

**Key insight**: Request type strongly predicts response format. Token-based APIs prefer JSON, lookup-based systems prefer HTML.

## Bin Selector Patterns

### By Response Format

| Format | With Selector | Without Selector | % With Selector |
|--------|---------------|------------------|-----------------|
| HTML | 194 | 3 | 98.5% |
| JSON | 26 | 75 | 25.7% |
| XML | 5 | 2 | 71.4% |

**Key insight**: JSON responses rarely need selectors (already structured), HTML almost always needs selectors.

### HTML Selector Patterns (194 councils)

#### Structural Categories
- **Table-based**: 52 councils (27%) - Select `tr` elements from tables
- **List-based**: 42 councils (22%) - Select `li` elements from lists
- **Div-based**: 63 councils (32%) - Select div containers
- **Semantic keywords**: 87 councils (45%) - Include `bin`, `waste`, `collection`, `refuse`, `recycling`

#### Final Element Types
- `div`: 60 councils (31%)
- `tr`: 37 councils (19%)
- `li`: 22 councils (11%)
- `h3`: 10 councils (5%)
- `table`: 8 councils (4%)

#### Common Selectors (used by 2+ councils)
- `h3`: 4 councils
- `h3.waste-service-name`: 3 councils
- `tr`: 3 councils
- `table tbody tr`: 3 councils
- `ul.refuse li`: 3 councils

#### Complexity Breakdown
- Simple element only (e.g., `tr`, `li`): 16 councils (8%)
- Has class (`.`): 131 councils (68%)
- Has ID (`#`): 24 councils (12%)
- Has attribute selector (`[]`): 21 councils (11%)
- Multiple selectors (`,`): 14 councils (7%)

### JSON Selector Patterns (26 councils)

#### Pattern Types
- **Dot notation** (JSONPath-like): 10 councils
  - Examples: `integration.transformed.rows_data`, `GetBinCollectionResult.Data`
- **Simple keys**: 15 councils
  - Examples: `collections`, `lstNextCollections`, `BinCollections`
- **Path-like** (slash notation): 1 council
  - Example: `results/collections/all`

**Key insight**: Most JSON (74%) doesn't need selectors. When needed, selectors are JSONPath expressions for nested data.

## Date Format Patterns

### Format Style Distribution
- **Python strftime**: 269 councils (88.2%)
- **Java-style**: 29 councils (9.5%) - e.g., `dd/MM/yyyy`, `DD/MM/YYYY`
- **ISO keywords**: 7 councils (2.3%) - e.g., `ISO`, `YYYY-MM-DD`

### Top 10 Most Common Formats
1. `%d/%m/%Y`: 60 councils (19.7%)
2. `%A %d %B %Y`: 31 councils (10.2%)
3. `%Y-%m-%d`: 26 councils (8.5%)
4. `%d %B %Y`: 26 councils (8.5%)
5. `%A %d %B`: 21 councils (6.9%)
6. `%A, %d %B %Y`: 15 councils (4.9%)
7. `%Y-%m-%dT%H:%M:%S`: 15 councils (4.9%)
8. `%d/%m/%Y %H:%M:%S`: 7 councils (2.3%)
9. `dd/MM/yyyy`: 6 councils (2.0%)
10. `%A %d/%m/%Y`: 6 councils (2.0%)

**Top 5 formats cover 72% of all councils**

## Semantic Keyword Patterns

### HTML Class Names (Most Common Keywords)
- `collection`: 21 occurrences
- `table`: 20 occurrences
- `bin`: 19 occurrences
- `waste`: 12 occurrences
- `service`: 8 occurrences
- `item`: 8 occurrences
- `row`: 8 occurrences

### HTML ID Names (Most Common Keywords)
- `collections`: 5 occurrences
- `scheduled`: 4 occurrences
- `collection`: 2 occurrences

**Key insight**: 45% of HTML selectors contain semantic keywords, providing strong signals for heuristic detection.

## Parser Design Recommendations

### Option A: Hybrid Approach (Recommended)

**Date Parsing**: Use heuristics with fallback
- Try fuzzy parsing (e.g., day.js, date-fns)
- Fallback to explicit `date_format` if fuzzy parsing fails
- Could eliminate explicit format for 90%+ of councils

**JSON Parsing**: Use heuristics with fallback
- Auto-detect bin arrays using common keys and structure analysis
- Fallback to explicit `bin_selector` for the 26 edge cases
- Could eliminate selectors for ~75% of JSON councils

**HTML Parsing**: Use scored heuristics with fallback
- Score potential bin containers based on:
  - Semantic keywords in classes/IDs
  - Structural patterns (tables, lists, repeated divs)
  - Date patterns in content
  - Element repetition
- Fallback to explicit `bin_selector` for low-confidence results
- Could eliminate selectors for ~60-70% of HTML councils

### Expected Coverage
- **Total councils**: 306
- **Heuristics only**: ~180-200 councils (59-65%)
- **Requires explicit selectors**: ~100-120 councils (33-39%)
- **Configuration reduction**: ~67% fewer manual specifications

## Implementation Notes

### High-Confidence Heuristics (Safe to automate)
- JSON with null selector (75 councils) - very structured
- HTML tables with `tr` patterns (52 councils) - clear structure
- Date parsing with fuzzy parser (269+ councils) - robust libraries

### Medium-Confidence Heuristics (Needs validation)
- HTML lists with `li` patterns (42 councils) - usually clear
- HTML divs with semantic keywords (87 councils) - varies in complexity
- JSON with nested paths (26 councils) - need smart traversal

### Low-Confidence Cases (Keep explicit config)
- Complex multi-selector HTML (14 councils)
- Attribute-based selectors (21 councils)
- XML parsing (7 councils)
- Highly nested/unusual HTML structures

## Next Steps

1. Build JavaScript parser with hybrid approach
2. Test against representative sample from each category
3. Identify failure cases and refine heuristics
4. Gradually remove explicit selectors as confidence improves
5. Monitor parser success rates and add targeted rules for failures
