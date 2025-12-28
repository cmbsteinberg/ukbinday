/**
 * Cloudflare Worker - CORS Proxy for UK Bin Lookup
 *
 * This worker acts as a CORS proxy, allowing the client-side application
 * to make requests to council APIs that don't support CORS.
 *
 * Security Notes:
 * - Only accepts POST requests with JSON body
 * - Validates request structure
 * - Rate limiting should be configured in Cloudflare dashboard
 */

export default {
  async fetch(request, env, ctx) {
    // Handle CORS preflight requests
    if (request.method === 'OPTIONS') {
      return handleOptions();
    }

    // Only allow POST requests
    if (request.method !== 'POST') {
      return new Response('Method not allowed. Use POST.', {
        status: 405,
        headers: corsHeaders(),
      });
    }

    try {
      // Parse the request from the client
      const requestData = await request.json();

      // Validate request structure
      if (!requestData.url || !requestData.method) {
        return new Response(JSON.stringify({ error: 'Invalid request. Missing url or method.' }), {
          status: 400,
          headers: {
            'Content-Type': 'application/json',
            ...corsHeaders(),
          },
        });
      }

      const { url, method, headers, body } = requestData;

      // Validate URL (basic check)
      try {
        new URL(url);
      } catch {
        return new Response(JSON.stringify({ error: 'Invalid URL' }), {
          status: 400,
          headers: {
            'Content-Type': 'application/json',
            ...corsHeaders(),
          },
        });
      }

      // Prepare the request to the council API
      const fetchOptions = {
        method: method,
        headers: headers || {},
      };

      // Add body if present
      if (body && method === 'POST') {
        if (typeof body === 'object') {
          fetchOptions.body = JSON.stringify(body);
          if (!fetchOptions.headers['Content-Type']) {
            fetchOptions.headers['Content-Type'] = 'application/json';
          }
        } else {
          fetchOptions.body = body;
        }
      }

      // Make the request to the council API
      console.log(`Proxying ${method} request to: ${url}`);

      const councilResponse = await fetch(url, fetchOptions);

      // Get response body
      const responseBody = await councilResponse.text();
      const responseContentType = councilResponse.headers.get('Content-Type') || 'text/plain';

      // Return response with CORS headers
      return new Response(responseBody, {
        status: councilResponse.status,
        statusText: councilResponse.statusText,
        headers: {
          'Content-Type': responseContentType,
          ...corsHeaders(),
        },
      });
    } catch (error) {
      console.error('CORS Proxy Error:', error);

      return new Response(
        JSON.stringify({
          error: 'Proxy error',
          message: error.message,
        }),
        {
          status: 500,
          headers: {
            'Content-Type': 'application/json',
            ...corsHeaders(),
          },
        },
      );
    }
  },
};

/**
 * Handle CORS preflight OPTIONS requests
 */
function handleOptions() {
  return new Response(null, {
    status: 204,
    headers: {
      ...corsHeaders(),
      'Access-Control-Max-Age': '86400', // 24 hours
    },
  });
}

/**
 * CORS headers to allow browser requests
 */
function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*', // In production, restrict this to your domain
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Expose-Headers': 'Content-Type',
  };
}
