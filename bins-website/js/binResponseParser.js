/**
 * Bin Response Parser - Heuristic-based parser for council bin data
 *
 * Parses bin collection data from various council response formats (JSON, HTML, XML)
 * using intelligent heuristics with fallback to explicit selectors.
 *
 * Approach: Hybrid (Option A)
 * - Attempt heuristic parsing first for maximum simplicity
 * - Fall back to explicit selectors from council config when needed
 * - Provide confidence scores to indicate parsing reliability
 *
 * No external dependencies - vanilla JavaScript only.
 */

// ============================================================================
// DATE PARSING
// ============================================================================

/**
 * Common date format patterns (Python strftime to JS mapping)
 */
const COMMON_DATE_FORMATS = [
  { format: '%d/%m/%Y', regex: /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/, parse: parseDMY },
  {
    format: '%A %d %B %Y',
    regex:
      /^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2})\s+(\w+)\s+(\d{4})$/i,
    parse: parseDayDayMonthYear,
  },
  { format: '%Y-%m-%d', regex: /^(\d{4})-(\d{2})-(\d{2})$/, parse: parseYMD },
  {
    format: '%d %B %Y',
    regex: /^(\d{1,2})\s+(\w+)\s+(\d{4})$/,
    parse: parseDayMonthYear,
  },
  {
    format: '%A %d %B',
    regex: /^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2})\s+(\w+)$/i,
    parse: parseDayDayMonth,
  },
  {
    format: '%A, %d %B %Y',
    regex:
      /^(monday|tuesday|wednesday|thursday|friday|saturday|sunday),\s*(\d{1,2})\s+(\w+)\s+(\d{4})$/i,
    parse: parseDayDayMonthYear,
  },
  {
    format: '%Y-%m-%dT%H:%M:%S',
    regex: /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/,
    parse: parseISO,
  },
  {
    format: '%d/%m/%Y %H:%M:%S',
    regex: /^(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})$/,
    parse: parseDMYTime,
  },
];

const MONTH_NAMES = {
  january: 0,
  february: 1,
  march: 2,
  april: 3,
  may: 4,
  june: 5,
  july: 6,
  august: 7,
  september: 8,
  october: 9,
  november: 10,
  december: 11,
  jan: 0,
  feb: 1,
  mar: 2,
  apr: 3,
  jun: 6,
  jul: 7,
  aug: 8,
  sep: 9,
  oct: 10,
  nov: 11,
  dec: 11,
};

function parseDMY(matches) {
  const [, day, month, year] = matches;
  return new Date(Number.parseInt(year), Number.parseInt(month) - 1, Number.parseInt(day));
}

function parseYMD(matches) {
  const [, year, month, day] = matches;
  return new Date(Number.parseInt(year), Number.parseInt(month) - 1, Number.parseInt(day));
}

function parseDayMonthYear(matches) {
  const [, day, monthName, year] = matches;
  const month = MONTH_NAMES[monthName.toLowerCase()];
  if (month === undefined) return null;
  return new Date(Number.parseInt(year), month, Number.parseInt(day));
}

function parseDayDayMonthYear(matches) {
  const [, , day, monthName, year] = matches;
  const month = MONTH_NAMES[monthName.toLowerCase()];
  if (month === undefined) return null;
  return new Date(Number.parseInt(year), month, Number.parseInt(day));
}

function parseDayDayMonth(matches) {
  const [, , day, monthName] = matches;
  const month = MONTH_NAMES[monthName.toLowerCase()];
  if (month === undefined) return null;
  const currentYear = new Date().getFullYear();
  return new Date(currentYear, month, Number.parseInt(day));
}

function parseISO(matches) {
  const [, year, month, day, hours, minutes, seconds] = matches;
  return new Date(
    Number.parseInt(year),
    Number.parseInt(month) - 1,
    Number.parseInt(day),
    Number.parseInt(hours),
    Number.parseInt(minutes),
    Number.parseInt(seconds),
  );
}

function parseDMYTime(matches) {
  const [, day, month, year, hours, minutes, seconds] = matches;
  return new Date(
    Number.parseInt(year),
    Number.parseInt(month) - 1,
    Number.parseInt(day),
    Number.parseInt(hours),
    Number.parseInt(minutes),
    Number.parseInt(seconds),
  );
}

/**
 * Check if text contains date-like patterns
 */
function hasDatePattern(text) {
  if (!text) return false;
  const textStr = text.toString();

  const datePatterns = [
    /\d{1,2}[/-]\d{1,2}[/-]\d{2,4}/, // 25/12/2024
    /\d{4}-\d{2}-\d{2}/, // 2024-12-25
    /\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/i, // 25 Dec
    /(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}/i,
    /(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)/i,
  ];

  return datePatterns.some((pattern) => pattern.test(textStr));
}

/**
 * Parse date string using heuristics
 * Tries common formats first, then falls back to native Date parsing
 */
function parseDate(dateString, explicitFormat = null) {
  if (!dateString) return null;

  const cleaned = dateString.toString().trim();

  // If explicit format provided, try it first (not implemented in this version)
  // This would require a full strftime parser

  // Try common formats
  for (const { regex, parse } of COMMON_DATE_FORMATS) {
    const match = cleaned.match(regex);
    if (match) {
      const date = parse(match);
      if (date && !Number.isNaN(date.getTime())) {
        return date;
      }
    }
  }

  // Fallback: Native Date parsing (handles ISO and many formats)
  const nativeDate = new Date(cleaned);
  if (!Number.isNaN(nativeDate.getTime())) {
    return nativeDate;
  }

  // Failed to parse
  console.warn(`Could not parse date: "${dateString}"`);
  return null;
}

// ============================================================================
// JSON PARSING
// ============================================================================

/**
 * Common keys used for bin collection arrays in JSON responses
 */
const COMMON_BIN_KEYS = [
  'collections',
  'bins',
  'data',
  'results',
  'rows_data',
  'BinCollections',
  'all',
  'items',
  'services',
];

/**
 * Check if an object looks like a bin collection entry
 */
function looksLikeBinEntry(obj) {
  if (!obj || typeof obj !== 'object') return false;

  const dateKeys = [
    'date',
    'collection_date',
    'next_date',
    'collectionDate',
    'Date',
    'NextCollection',
    'nextCollection',
  ];
  const typeKeys = ['type', 'bin_type', 'binType', 'service', 'serviceName', 'name'];

  // Check for date-like keys
  const hasDateKey = dateKeys.some((key) => key in obj);

  // Check for type/service keys
  const hasTypeKey = typeKeys.some((key) => key in obj);

  // Check if any value looks like a date
  const hasDateValue = Object.values(obj).some(
    (val) => typeof val === 'string' && hasDatePattern(val),
  );

  // Check for bin-related keywords
  const hasKeywords = Object.keys(obj).some((key) =>
    /bin|waste|collection|refuse|recycling/i.test(key),
  );

  // Score the likelihood
  let score = 0;
  if (hasDateKey) score += 3;
  if (hasTypeKey) score += 2;
  if (hasDateValue) score += 2;
  if (hasKeywords) score += 1;

  return score >= 3;
}

/**
 * Find arrays that likely contain bin collection data
 */
function findBinArrays(obj, path = '') {
  const candidates = [];

  if (Array.isArray(obj)) {
    // Check if this array contains bin-like objects
    if (obj.length > 0) {
      const score = obj.slice(0, 3).filter((item) => looksLikeBinEntry(item)).length;
      if (score > 0) {
        candidates.push({
          path,
          data: obj,
          score: score * 10,
        });
      }
    }
  } else if (obj && typeof obj === 'object') {
    // Recurse into object properties
    for (const [key, value] of Object.entries(obj)) {
      const newPath = path ? `${path}.${key}` : key;

      // Bonus score for semantic keys
      let bonus = 0;
      if (COMMON_BIN_KEYS.includes(key)) {
        bonus = 20;
      } else if (/collection|bin|waste|refuse/i.test(key)) {
        bonus = 10;
      }

      const subCandidates = findBinArrays(value, newPath);
      for (const candidate of subCandidates) {
        candidate.score += bonus;
      }

      candidates.push(...subCandidates);
    }
  }

  return candidates;
}

/**
 * Parse JSON response using heuristics
 */
function parseJsonResponse(data, binSelector = null) {
  // If explicit selector provided, use it
  if (binSelector) {
    try {
      const result = getValueByPath(data, binSelector);
      if (result) {
        return {
          bins: Array.isArray(result) ? result : [result],
          confidence: 'high',
          method: 'explicit_selector',
        };
      }
    } catch (error) {
      console.warn(`Explicit selector failed: ${binSelector}`, error);
    }
  }

  // Heuristic approach

  // Strategy 1: Data is already an array of bins
  if (Array.isArray(data) && data.length > 0 && looksLikeBinEntry(data[0])) {
    return {
      bins: data,
      confidence: 'high',
      method: 'root_array',
    };
  }

  // Strategy 2: Try common keys
  for (const key of COMMON_BIN_KEYS) {
    if (key in data && Array.isArray(data[key]) && data[key].length > 0) {
      if (looksLikeBinEntry(data[key][0])) {
        return {
          bins: data[key],
          confidence: 'high',
          method: 'common_key',
          key,
        };
      }
    }
  }

  // Strategy 3: Deep search for arrays
  const candidates = findBinArrays(data);
  if (candidates.length > 0) {
    // Sort by score
    candidates.sort((a, b) => b.score - a.score);
    const best = candidates[0];

    return {
      bins: best.data,
      confidence: best.score >= 30 ? 'high' : best.score >= 20 ? 'medium' : 'low',
      method: 'deep_search',
      path: best.path,
    };
  }

  // Failed to find bins
  return {
    bins: [],
    confidence: 'none',
    method: 'failed',
    rawData: data,
  };
}

/**
 * Get value from object using dot notation path
 */
function getValueByPath(obj, path) {
  // Support both dot notation and slash notation
  const parts = path.includes('/') ? path.split('/') : path.split('.');
  let current = obj;

  for (const part of parts) {
    if (current === null || current === undefined) return null;
    current = current[part];
  }

  return current;
}

// ============================================================================
// HTML PARSING
// ============================================================================

/**
 * Check if text contains bin-related keywords
 */
function hasBinKeywords(text) {
  if (!text) return false;
  const keywords = ['bin', 'waste', 'collection', 'refuse', 'recycling', 'garden', 'food'];
  const textLower = text.toLowerCase();
  return keywords.some((keyword) => textLower.includes(keyword));
}

/**
 * Score elements as potential bin collection entries
 */
function scoreElements(elements, parentElement = null) {
  if (!elements || elements.length === 0) return 0;

  let score = 0;
  const sample = Array.from(elements).slice(0, 5);

  for (const elem of sample) {
    const text = elem.textContent || '';

    // +10 for each date pattern found
    if (hasDatePattern(text)) {
      score += 10;
    }

    // +5 for bin keywords
    if (hasBinKeywords(text)) {
      score += 5;
    }

    // +3 for day names
    if (/(monday|tuesday|wednesday|thursday|friday|saturday|sunday)/i.test(text)) {
      score += 3;
    }
  }

  // Bonus for multiple elements (structural repetition)
  if (elements.length >= 3) {
    score += 10;
  }

  // Bonus if parent has semantic keywords
  if (parentElement) {
    const parentClass = (parentElement.className || '').toString();
    const parentId = parentElement.id || '';
    const parentAttrs = `${parentClass} ${parentId}`.toLowerCase();

    if (/bin|waste|collection|refuse/i.test(parentAttrs)) {
      score += 15;
    }
  }

  // Penalty if elements are very short (likely not bin data)
  const avgLength =
    sample.reduce((sum, elem) => sum + (elem.textContent || '').trim().length, 0) / sample.length;
  if (avgLength < 10) {
    score -= 10;
  }

  return score;
}

/**
 * Find bin collection elements in HTML using heuristics
 */
function findBinsInHtml(doc) {
  const candidates = [];

  // Strategy 1: Table rows
  const tables = doc.querySelectorAll('table');
  for (const table of tables) {
    const rows = Array.from(table.querySelectorAll('tr')).slice(1); // Skip header
    if (rows.length >= 2) {
      const score = scoreElements(rows, table);
      if (score > 0) {
        candidates.push({
          elements: rows,
          selector: 'tr',
          score,
          type: 'table',
        });
      }
    }
  }

  // Strategy 2: List items
  const lists = doc.querySelectorAll('ul, ol');
  for (const list of lists) {
    const items = Array.from(list.children).filter((child) => child.tagName === 'LI');
    if (items.length >= 2) {
      const score = scoreElements(items, list);
      if (score > 0) {
        candidates.push({
          elements: items,
          selector: 'li',
          score,
          type: 'list',
        });
      }
    }
  }

  // Strategy 3: Divs with semantic classes
  const semanticKeywords = ['bin', 'waste', 'collection', 'refuse', 'recycling', 'service'];

  for (const keyword of semanticKeywords) {
    const containers = doc.querySelectorAll(`div[class*="${keyword}" i]`);

    for (const container of containers) {
      // Check for sibling pattern
      const className = container.className;
      if (className) {
        const siblings = Array.from(container.parentElement?.children || []).filter(
          (sibling) => sibling.tagName === 'DIV' && sibling.className === className,
        );

        if (siblings.length >= 2) {
          const score = scoreElements(siblings, container.parentElement);
          if (score > 0) {
            candidates.push({
              elements: siblings,
              selector: `div.${className.split(' ')[0]}`,
              score,
              type: 'div-siblings',
            });
          }
        }
      }

      // Check for children
      const children = Array.from(container.children);
      if (children.length >= 2) {
        const score = scoreElements(children, container);
        if (score > 0) {
          candidates.push({
            elements: children,
            selector: `${container.tagName.toLowerCase()}#${container.id || container.className} > *`,
            score,
            type: 'div-children',
          });
        }
      }
    }
  }

  // Strategy 4: Headings (h2, h3, etc.) - often used for bin types
  for (const tag of ['h2', 'h3', 'h4']) {
    const headings = Array.from(doc.querySelectorAll(tag));
    const binHeadings = headings.filter((h) => hasBinKeywords(h.textContent || ''));

    if (binHeadings.length >= 2) {
      const score = scoreElements(binHeadings);
      if (score > 0) {
        candidates.push({
          elements: binHeadings,
          selector: tag,
          score,
          type: 'headings',
        });
      }
    }
  }

  // Return highest scoring candidate
  if (candidates.length > 0) {
    candidates.sort((a, b) => b.score - a.score);
    const best = candidates[0];
    return {
      elements: best.elements,
      confidence: best.score >= 40 ? 'high' : best.score >= 25 ? 'medium' : 'low',
      method: 'heuristic',
      selector: best.selector,
      score: best.score,
    };
  }

  return {
    elements: [],
    confidence: 'none',
    method: 'failed',
  };
}

/**
 * Parse HTML response
 */
function parseHtmlResponse(html, binSelector = null) {
  // Parse HTML
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');

  // If explicit selector provided, try it first
  if (binSelector) {
    try {
      const elements = doc.querySelectorAll(binSelector);
      if (elements.length > 0) {
        return {
          elements: Array.from(elements),
          confidence: 'high',
          method: 'explicit_selector',
          selector: binSelector,
        };
      }
    } catch (error) {
      console.warn(`Explicit selector failed: ${binSelector}`, error);
    }
  }

  // Use heuristics
  return findBinsInHtml(doc);
}

// ============================================================================
// XML PARSING
// ============================================================================

/**
 * Parse XML response (basic implementation)
 */
function parseXmlResponse(xml, binSelector = null) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xml, 'text/xml');

  if (binSelector) {
    const elements = doc.querySelectorAll(binSelector);
    if (elements.length > 0) {
      return {
        elements: Array.from(elements),
        confidence: 'high',
        method: 'explicit_selector',
      };
    }
  }

  // Fallback: find all repeating elements
  const allElements = Array.from(doc.documentElement.children);
  if (allElements.length > 0) {
    return {
      elements: allElements,
      confidence: 'medium',
      method: 'root_children',
    };
  }

  return {
    elements: [],
    confidence: 'none',
    method: 'failed',
  };
}

// ============================================================================
// MAIN PARSER
// ============================================================================

/**
 * Parse bin collection response
 *
 * @param {string|object} response - Raw response from council API
 * @param {object} councilConfig - Council configuration from councils-data.json
 * @returns {object} Parsed bin collection data with metadata
 */
function parseBinResponse(response, councilConfig) {
  const responseFormat = councilConfig.response_format || 'html';
  const binSelector = councilConfig.bin_selector || null;
  const dateFormat = councilConfig.date_format || null;

  let parseResult;

  // Parse based on format
  if (responseFormat === 'json') {
    const data = typeof response === 'string' ? JSON.parse(response) : response;
    parseResult = parseJsonResponse(data, binSelector);

    // Extract bin data from JSON objects
    if (parseResult.bins && parseResult.bins.length > 0) {
      parseResult.collections = parseResult.bins.map((bin) => extractBinFromJson(bin, dateFormat));
    }
  } else if (responseFormat === 'html') {
    const html = typeof response === 'object' ? JSON.stringify(response) : response;
    parseResult = parseHtmlResponse(html, binSelector);

    // Extract bin data from HTML elements
    if (parseResult.elements && parseResult.elements.length > 0) {
      parseResult.collections = parseResult.elements.map((elem) =>
        extractBinFromHtml(elem, dateFormat),
      );
    }
  } else if (responseFormat === 'xml') {
    const xml = typeof response === 'object' ? JSON.stringify(response) : response;
    parseResult = parseXmlResponse(xml, binSelector);

    // Extract bin data from XML elements
    if (parseResult.elements && parseResult.elements.length > 0) {
      parseResult.collections = parseResult.elements.map((elem) =>
        extractBinFromXml(elem, dateFormat),
      );
    }
  } else {
    throw new Error(`Unsupported response format: ${responseFormat}`);
  }

  // Filter out invalid collections
  if (parseResult.collections) {
    parseResult.collections = parseResult.collections.filter((c) => c.date !== null);
  }

  return parseResult;
}

/**
 * Extract bin information from JSON object
 */
function extractBinFromJson(binObj, dateFormat = null) {
  // Find date field
  const dateKeys = [
    'date',
    'collection_date',
    'next_date',
    'collectionDate',
    'Date',
    'NextCollection',
    'nextCollection',
  ];
  let dateValue = null;

  for (const key of dateKeys) {
    if (key in binObj) {
      dateValue = binObj[key];
      break;
    }
  }

  // If no explicit date key, look for date-like values
  if (!dateValue) {
    for (const value of Object.values(binObj)) {
      if (typeof value === 'string' && hasDatePattern(value)) {
        dateValue = value;
        break;
      }
    }
  }

  // Find type field
  const typeKeys = ['type', 'bin_type', 'binType', 'service', 'serviceName', 'name', 'BinType'];
  let typeValue = 'Unknown';

  for (const key of typeKeys) {
    if (key in binObj && binObj[key]) {
      typeValue = binObj[key];
      break;
    }
  }

  return {
    type: typeValue,
    date: parseDate(dateValue, dateFormat),
    rawDate: dateValue,
    raw: binObj,
  };
}

/**
 * Extract bin information from HTML element
 */
function extractBinFromHtml(element, dateFormat = null) {
  const text = element.textContent || '';

  // Try to find date in text
  const dateMatch = text.match(
    /\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|(monday|tuesday|wednesday|thursday|friday|saturday|sunday)[,\s]+\d{1,2}\s+\w+/i,
  );
  const dateValue = dateMatch ? dateMatch[0] : text;

  // Type is the remaining text or full text
  let typeValue = text.trim();
  if (dateMatch) {
    typeValue = text.replace(dateMatch[0], '').trim() || 'Collection';
  }

  return {
    type: typeValue,
    date: parseDate(dateValue, dateFormat),
    rawDate: dateValue,
    element: element,
  };
}

/**
 * Extract bin information from XML element
 */
function extractBinFromXml(element, dateFormat = null) {
  // Try common attribute/child names
  const dateValue =
    element.getAttribute('date') ||
    element.getAttribute('Date') ||
    element.querySelector('date, Date, CollectionDate')?.textContent ||
    element.textContent;

  const typeValue =
    element.getAttribute('type') ||
    element.getAttribute('Type') ||
    element.querySelector('type, Type, BinType')?.textContent ||
    'Collection';

  return {
    type: typeValue,
    date: parseDate(dateValue, dateFormat),
    rawDate: dateValue,
    element: element,
  };
}

// ============================================================================
// EXPORTS
// ============================================================================

// For use in browsers (attach to window)
if (typeof window !== 'undefined') {
  window.BinResponseParser = {
    parseBinResponse,
    parseDate,
    parseJsonResponse,
    parseHtmlResponse,
    parseXmlResponse,
  };
}

// For use in Node.js (if needed for testing)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    parseBinResponse,
    parseDate,
    parseJsonResponse,
    parseHtmlResponse,
    parseXmlResponse,
  };
}
