TASK

Use Playwright MCP to discover different workflows for 10 different local authorities in the UK.

**RESILIENCE STRATEGY**: Treat each council independently. If one fails, document it and continue to the next. Don't let failures cascade.

**OPTIMIZATION STRATEGY**:
- Use `browser_run_code` to **batch all operations you can do on the current page** (saves 70-80% tokens vs individual commands)
- After each page/action, **inspect the result** to decide what to do next
- Extract data immediately when you see it - don't wait until the end
- Only take snapshots when `run_code` fails and you need to debug

## Workflow

1. Run playwright/cc/read_csv.sh to see the top 11 lines of a csv containing the following columns:
[Authority Name,GSS,URL,sitemap_url,waste_collection_urls,Number,Street,Town,Address,postcode]
Process the first 10 entries. Use the URL, and Address columns.

**PRE-FLIGHT CHECK**: If Address/postcode columns are empty, mark as "Skipped - No address data" and move to next council.

2. **NAVIGATE to council website**:
   - If waste_collection_urls is present and not empty, navigate directly to the first URL in that list
   - Otherwise, go to the main URL: `playwright - Navigate to a URL (url: "URL")`

3. **EXPLORE AND INTERACT** - Each council is different, so adapt based on what you find:

   **General principle**: At each step, use `run_code` to batch everything you can do on the current page, then inspect what you got.

   **Common patterns you might encounter:**

   a. **Cookie banners** - Handle on first page:
   ```javascript
   playwright - Run code (code: "async (page) => {
     try {
       await page.click('button:has-text(\"Accept\")', { timeout: 3000 });
       await page.waitForTimeout(1000);
     } catch {}
     return { cookie_handled: true };
   }")
   ```

   b. **Finding bin collection form** - If not already on it:
   ```javascript
   playwright - Run code (code: "async (page) => {
     // Check if already on bin form
     const hasPostcode = await page.locator('input[placeholder*=\"postcode\"]').count() > 0;
     if (hasPostcode) return { status: 'found', location: 'current_page' };

     // Look for bin/waste links
     const link = page.locator('a:has-text(\"bin\"), a:has-text(\"waste\")').first();
     if (await link.count() > 0) {
       const url = await link.getAttribute('href');
       await link.click();
       await page.waitForLoadState('networkidle');
       return { status: 'navigated', url };
     }

     return { status: 'not_found' };
   }")
   ```

   c. **Postcode entry + address search** - Batch these together:
   ```javascript
   playwright - Run code (code: "async (page) => {
     const postcode = 'PE19 0AA';  // from CSV

     // Check for iframe (some councils use embedded forms)
     let context = page;
     if (await page.locator('iframe').count() > 0) {
       context = page.frameLocator('iframe').first();
     }

     // Fill postcode and search
     await context.locator('input[placeholder*=\"postcode\"]').first().fill(postcode);
     await context.locator('button:has-text(\"Search\"), button:has-text(\"Find\")').first().click();
     await page.waitForTimeout(2000);

     // Get available addresses
     const dropdown = context.locator('select, [role=\"combobox\"]').first();
     const addresses = await dropdown.locator('option').allTextContents();

     return { addresses, postcode };
   }")
   ```
   - Inspect the addresses returned
   - Pick the one matching CSV or closest match

   d. **Select address + submit** - Batch these:
   ```javascript
   playwright - Run code (code: "async (page) => {
     const address = '69 NUFFIELD ROAD, ST NEOTS, PE190AA';  // from your decision

     let context = page;
     if (await page.locator('iframe').count() > 0) {
       context = page.frameLocator('iframe').first();
     }

     await context.locator('select').first().selectOption(address);
     await context.locator('button:has-text(\"Continue\"), a:has-text(\"View\")').first().click();
     await page.waitForLoadState('networkidle');

     return { status: 'submitted', address };
   }")
   ```

   e. **Extract bin data** - Get everything you can see:
   ```javascript
   playwright - Run code (code: "async (page) => {
     const binData = [];

     // Try different patterns councils use
     const selectors = [
       'li:has-text(\"bin\"), li:has-text(\"waste\")',
       'tr:has-text(\"collection\")',
       'p:has-text(\"next collection\")',
       'div[class*=\"bin\"], div[class*=\"waste\"]'
     ];

     for (const selector of selectors) {
       const elements = await page.locator(selector).all();
       if (elements.length > 0) {
         for (const el of elements) {
           const text = await el.textContent();
           if (text && text.length > 10) binData.push(text.trim());
         }
         break;
       }
     }

     return { bins: binData, success: binData.length > 0 };
   }")
   ```

4. **ADAPT TO THE WORKFLOW**:
   - Some councils might be single-page (enter postcode → see results immediately)
   - Some might have multi-step wizards (postcode → select address → view calendar → see dates)
   - Some might require login or have service suspensions
   - Use `run_code` to batch operations on each page, then decide next step based on results

**ERROR HANDLING**:
- If `run_code` fails, fall back to individual MCP commands (Click, Type, etc.) with snapshots for debugging
- If modal dialog appears, handle with `playwright - Handle dialog`, then continue
- If page navigation fails: mark as "Fail - Navigation error" and move to next council
- If service unavailable message appears: mark as "Fail - Service suspended" and move on
- Maximum 3 minutes per council - if exceeded, mark as "Fail - Timeout" and move on

**IMPORTANT**: Process councils **sequentially** (one at a time). Playwright MCP uses a single browser instance and cannot run multiple councils in parallel.

**OUTPUT REQUIREMENT**: Return a structured Markdown table with the following columns:
| Authority | Address Used | Bin Type | Next Collection Date | Status | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |

Status values:
- "Success" - Data extracted successfully
- "Fail - <reason>" - Attempted but failed (specify: Service suspended, No collections found, Timeout, Navigation error, etc.)
- "Skipped - <reason>" - Not attempted (specify: No address data, Browser issue, etc.)

## Example: Adaptive Workflow

**Huntingdonshire (multi-page workflow):**
```
1. Navigate to waste_collection_url
2. Run code: dismiss cookie + check page state
   → Found postcode form on current page
3. Run code: enter postcode + search + get addresses
   → Returns: { addresses: ['69 NUFFIELD...', '71 NUFFIELD...'] }
4. Run code: select '69 NUFFIELD ROAD' + click 'View Calendar'
   → Navigates to results page
5. Run code: extract all bin types and dates
   → Returns: { bins: ['Domestic: Mon 05 Jan', 'Recycling: Mon 29 Dec'] }
```

**Hypothetical single-page council:**
```
1. Navigate to waste_collection_url
2. Run code: dismiss cookie + enter postcode + auto-extract results
   → Returns: { bins: [...] } immediately
```

**Why this works:**
- Batches operations per page (saves 70-80% tokens)
- Adapts to different council workflows
- Inspects results between steps to decide what's needed next
- Falls back gracefully when things fail
