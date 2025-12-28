/**
 * Integration tests for bins-website
 *
 * Tests the core functionality of app.js using test parameters from
 * councils-data.json
 */

const fs = require('fs');
const path = require('path');

// ============================================================================
// UTILITY FUNCTIONS (copied from app.js for testing)
// ============================================================================

/**
 * Validate UK postcode format
 */
function validatePostcode(postcode) {
  const regex = /^[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$/i;
  return regex.test(postcode.trim());
}

/**
 * Normalize postcode format (uppercase, with space)
 */
function normalizePostcode(postcode) {
  const clean = postcode.toUpperCase().replace(/\s/g, '');
  // Insert space before last 3 characters
  return `${clean.slice(0, -3)} ${clean.slice(-3)}`;
}

/**
 * Normalize address for comparison
 */
function normalizeAddress(address) {
  return address.replace(/[^a-z0-9]/gi, '').toLowerCase();
}

/**
 * Normalize council name (convert display name to config key)
 */
function normalizeCouncilName(councilDisplayName) {
  // Remove common suffixes and join words
  return councilDisplayName
    .replace(/\s+(City|Borough|District|County|Metropolitan|Unitary)\s+Council$/i, 'Council')
    .replace(/\s+Council$/i, 'Council')
    .replace(/\s+/g, '')
    .replace(/['-]/g, '');
}

/**
 * Build request configuration from council YAML config
 */
function buildCouncilRequest(councilConfig, inputs) {
  // Fill URL template
  let url = councilConfig.api_urls[0];
  for (const [key, value] of Object.entries(inputs)) {
    url = url.replace(`{${key}}`, encodeURIComponent(value));
  }

  // Prepare headers
  const headers = { ...councilConfig.api_headers };

  // Extract headers from description if present
  if (councilConfig.api_description) {
    const ocpMatch = councilConfig.api_description.match(
      /Ocp-Apim-Subscription-Key.*?['"]([a-f0-9]+)['"]/i,
    );
    if (ocpMatch) {
      headers['Ocp-Apim-Subscription-Key'] = ocpMatch[1];
    }
  }

  // Add default User-Agent if not present
  if (!headers['User-Agent']) {
    headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36';
  }

  const method = councilConfig.api_methods[0];

  // Prepare body for POST requests
  let body = null;
  if (method === 'POST') {
    const responseFormat = councilConfig.response_format;
    if (
      responseFormat === 'json' ||
      councilConfig.api_description?.toLowerCase().includes('json')
    ) {
      body = inputs;
      headers['Content-Type'] = 'application/json';
    } else {
      // Form data
      body = inputs;
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
    }
  }

  return { url, method, headers, body };
}

// ============================================================================
// TEST PARAMETER LOADING
// ============================================================================

/**
 * Load test parameters from councils-data.json
 */
function loadTestParameters() {
  const dataFile = path.join(__dirname, '../bins-website/data/councils-data.json');

  if (!fs.existsSync(dataFile)) {
    throw new Error(`Cannot find ${dataFile}`);
  }

  const councilsData = JSON.parse(fs.readFileSync(dataFile, 'utf8'));

  // Extract test inputs from each council
  const testParams = {};
  for (const [councilName, config] of Object.entries(councilsData)) {
    if (config.test_inputs) {
      testParams[councilName] = {
        config: config,
        inputs: config.test_inputs,
      };
    }
  }

  return testParams;
}

// ============================================================================
// TEST EXECUTION
// ============================================================================

/**
 * Test utility functions
 */
function testUtilityFunctions() {
  console.log('\n' + '='.repeat(80));
  console.log('Testing Utility Functions');
  console.log('='.repeat(80));

  const tests = [
    {
      name: 'validatePostcode - valid postcodes',
      fn: () => {
        const validPostcodes = ['SW1A 1AA', 'M1 1AE', 'B33 8TH', 'CR2 6XH', 'DN55 1PT'];
        for (const pc of validPostcodes) {
          if (!validatePostcode(pc)) {
            throw new Error(`Failed to validate valid postcode: ${pc}`);
          }
        }
      },
    },
    {
      name: 'validatePostcode - invalid postcodes',
      fn: () => {
        const invalidPostcodes = ['INVALID', '12345', 'A1', 'SW1A', ''];
        for (const pc of invalidPostcodes) {
          if (validatePostcode(pc)) {
            throw new Error(`Incorrectly validated invalid postcode: ${pc}`);
          }
        }
      },
    },
    {
      name: 'normalizePostcode',
      fn: () => {
        const tests = [
          { input: 'sw1a1aa', expected: 'SW1A 1AA' },
          { input: 'M1 1AE', expected: 'M1 1AE' },
          { input: 'b338th', expected: 'B33 8TH' },
        ];
        for (const test of tests) {
          const result = normalizePostcode(test.input);
          if (result !== test.expected) {
            throw new Error(
              `normalizePostcode(${test.input}) = ${result}, expected ${test.expected}`,
            );
          }
        }
      },
    },
    {
      name: 'normalizeAddress',
      fn: () => {
        const tests = [
          { input: '123 Main Street', expected: '123mainstreet' },
          { input: 'Flat 5, Oak House', expected: 'flat5oakhouse' },
          { input: "St. Mary's Road", expected: 'stmarysroad' },
        ];
        for (const test of tests) {
          const result = normalizeAddress(test.input);
          if (result !== test.expected) {
            throw new Error(
              `normalizeAddress(${test.input}) = ${result}, expected ${test.expected}`,
            );
          }
        }
      },
    },
    {
      name: 'normalizeCouncilName',
      fn: () => {
        const tests = [
          { input: 'Birmingham City Council', expected: 'BirminghamCouncil' },
          { input: 'Westminster Borough Council', expected: 'WestminsterCouncil' },
          { input: 'North-East Lincolnshire Council', expected: 'NorthEastLincolnshireCouncil' },
        ];
        for (const test of tests) {
          const result = normalizeCouncilName(test.input);
          if (result !== test.expected) {
            throw new Error(
              `normalizeCouncilName(${test.input}) = ${result}, expected ${test.expected}`,
            );
          }
        }
      },
    },
  ];

  let passed = 0;
  let failed = 0;

  for (const test of tests) {
    try {
      test.fn();
      console.log(`✅ ${test.name}`);
      passed++;
    } catch (error) {
      console.log(`❌ ${test.name}: ${error.message}`);
      failed++;
    }
  }

  console.log(
    `\nUtility Functions: ${passed} passed, ${failed} failed (${passed + failed} total)`,
  );

  return { passed, failed };
}

/**
 * Test buildCouncilRequest for a single council
 */
function testCouncilRequest(councilName, testData) {
  try {
    const { config, inputs } = testData;

    // Skip if no API URLs
    if (!config.api_urls || config.api_urls.length === 0) {
      return {
        council: councilName,
        status: 'skipped',
        reason: 'no_api_urls',
      };
    }

    // Build the request
    const request = buildCouncilRequest(config, inputs);

    // Validate request structure
    if (!request.url) {
      throw new Error('Missing URL in request');
    }

    if (!request.method) {
      throw new Error('Missing method in request');
    }

    // Validate URL has been properly filled
    if (request.url.includes('{') && request.url.includes('}')) {
      throw new Error('URL still contains template variables');
    }

    // Validate method
    if (!['GET', 'POST', 'PUT', 'DELETE'].includes(request.method)) {
      throw new Error(`Invalid HTTP method: ${request.method}`);
    }

    // Validate headers
    if (!request.headers || typeof request.headers !== 'object') {
      throw new Error('Invalid headers');
    }

    // Validate POST requests have Content-Type
    if (request.method === 'POST' && request.body !== null) {
      if (!request.headers['Content-Type']) {
        throw new Error('POST request missing Content-Type header');
      }
    }

    return {
      council: councilName,
      status: 'success',
      method: request.method,
      url_length: request.url.length,
      has_headers: Object.keys(request.headers).length > 0,
      has_body: request.body !== null,
    };
  } catch (error) {
    return {
      council: councilName,
      status: 'failed',
      error: error.message,
    };
  }
}

/**
 * Run integration tests for council request building
 */
function runIntegrationTests(maxTests = null, onlyCouncils = null) {
  console.log('\n' + '='.repeat(80));
  console.log('Council Request Building Integration Tests');
  console.log('='.repeat(80));

  // Load test parameters
  console.log('\nLoading test parameters from councils-data.json...');
  const testParams = loadTestParameters();
  console.log(`Loaded test parameters for ${Object.keys(testParams).length} councils`);

  // Filter councils to test
  let councilsToTest = Object.keys(testParams).sort();

  if (onlyCouncils) {
    councilsToTest = councilsToTest.filter((c) => onlyCouncils.includes(c));
  }

  if (maxTests) {
    councilsToTest = councilsToTest.slice(0, maxTests);
  }

  console.log(`\nTesting ${councilsToTest.length} councils\n`);

  // Run tests
  const results = [];
  let completed = 0;
  const total = councilsToTest.length;

  for (const councilName of councilsToTest) {
    const result = testCouncilRequest(councilName, testParams[councilName]);
    results.push(result);
    completed++;

    // Print status
    const statusMsg = `[${completed}/${total}] ${councilName}...`;
    if (result.status === 'success') {
      console.log(`${statusMsg} ✅ ${result.method}`);
    } else if (result.status === 'skipped') {
      console.log(`${statusMsg} ⏸️  ${result.reason}`);
    } else {
      console.log(`${statusMsg} ❌ ${result.error}`);
    }
  }

  // Calculate statistics
  const stats = {
    total: results.length,
    success: results.filter((r) => r.status === 'success').length,
    skipped: results.filter((r) => r.status === 'skipped').length,
    failed: results.filter((r) => r.status === 'failed').length,
    get_requests: results.filter((r) => r.method === 'GET').length,
    post_requests: results.filter((r) => r.method === 'POST').length,
  };

  // Print summary
  console.log('\n' + '='.repeat(80));
  console.log('Test Summary');
  console.log('='.repeat(80));
  console.log(`Total tested: ${stats.total}`);
  console.log(
    `  ✅ Success: ${stats.success} (${((stats.success / stats.total) * 100).toFixed(1)}%)`,
  );
  console.log(`  ⏸️  Skipped: ${stats.skipped}`);
  console.log(`  ❌ Failed: ${stats.failed}`);
  console.log(`\nRequest Methods:`);
  console.log(`  GET: ${stats.get_requests}`);
  console.log(`  POST: ${stats.post_requests}`);
  console.log('='.repeat(80));

  return {
    results,
    stats,
  };
}

// ============================================================================
// MAIN
// ============================================================================

function main() {
  const args = process.argv.slice(2);

  // Parse command line arguments
  let maxTests = null;
  let onlyCouncils = null;
  let saveResults = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--max' && args[i + 1]) {
      maxTests = parseInt(args[i + 1], 10);
      i++;
    } else if (args[i] === '--council' && args[i + 1]) {
      if (!onlyCouncils) onlyCouncils = [];
      onlyCouncils.push(args[i + 1]);
      i++;
    } else if (args[i] === '--save-results' && args[i + 1]) {
      saveResults = args[i + 1];
      i++;
    } else if (args[i] === '--help') {
      console.log(`
Usage: node test_bins_website.js [options]

Options:
  --max N                Maximum number of councils to test
  --council NAME         Test specific council (can be repeated)
  --save-results FILE    Save results to JSON file
  --help                 Show this help message
`);
      process.exit(0);
    }
  }

  // Run all tests
  const utilResults = testUtilityFunctions();
  const integrationResults = runIntegrationTests(maxTests, onlyCouncils);

  // Overall summary
  console.log('\n' + '='.repeat(80));
  console.log('Overall Test Summary');
  console.log('='.repeat(80));
  const totalPassed = utilResults.passed + integrationResults.stats.success;
  const totalFailed = utilResults.failed + integrationResults.stats.failed;
  const totalTests = totalPassed + totalFailed + integrationResults.stats.skipped;
  console.log(`Total: ${totalTests} tests`);
  console.log(`  ✅ Passed: ${totalPassed}`);
  console.log(`  ❌ Failed: ${totalFailed}`);
  console.log(`  ⏸️  Skipped: ${integrationResults.stats.skipped}`);
  console.log('='.repeat(80));

  // Save results if requested
  if (saveResults) {
    const output = {
      utility_tests: utilResults,
      integration_tests: integrationResults,
    };
    fs.writeFileSync(saveResults, JSON.stringify(output, null, 2));
    console.log(`\nResults saved to: ${saveResults}`);
  }

  // Exit with appropriate code
  process.exit(totalFailed > 0 ? 1 : 0);
}

if (require.main === module) {
  main();
}

module.exports = {
  validatePostcode,
  normalizePostcode,
  normalizeAddress,
  normalizeCouncilName,
  buildCouncilRequest,
  loadTestParameters,
  testCouncilRequest,
  runIntegrationTests,
};
