# UK Bin Collection Lookup

A simple, fast, client-side web application for looking up bin collection schedules across 300+ UK councils.

## Features

- 🗑️ Support for 306 UK councils with API-based lookups
- 🔍 Postcode-based address search
- 🚀 Fast, client-side JavaScript (no framework dependencies)
- 🎨 Beautiful responsive design with Pico CSS
- 🔒 Privacy-focused - no data storage, runs entirely in your browser
- ☁️ Deployed on Cloudflare Pages + Workers (free tier)

## Project Structure

```
bins-website/
├── index.html              # Main lookup page
├── about.html              # About page
├── js/
│   └── app.js             # Application logic
├── data/
│   └── councils-data.json # Council configurations (generated)
├── utils/
│   └── convert-yaml.py    # YAML → JSON converter
└── worker/
    ├── cors-proxy.js      # Cloudflare Worker (CORS proxy)
    └── wrangler.toml      # Worker configuration

Repository root:
├── package.json            # npm dependencies (Biome only)
├── biome.json             # Biome linter configuration
└── node_modules/          # npm packages
```

## Local Development

### Prerequisites

- Python 3.13+ (with `uv`)
- Node.js 18+ (for Biome linting)
- Modern web browser

### Setup

1. **Convert YAML configs to JSON:**
   ```bash
   npm run convert-yaml:local
   # or: python3 convert-yaml.py
   ```

   This generates `councils-data.json` (306 councils, ~232 KB)

2. **Install dev dependencies (optional, for linting):**
   ```bash
   npm install
   ```

3. **Open the website:**
   ```bash
   # Option 1: Use Python's built-in HTTP server
   python3 -m http.server 8000

   # Option 2: Just open index.html in your browser
   open index.html
   ```

4. **Visit:** http://localhost:8000

### Linting & Code Quality

```bash
# Run Biome linter and auto-fix
npm run check

# Format code
npm run format

# Lint only (no auto-fix)
npm run lint
```

## Deployment

### 1. Deploy the Cloudflare Worker (CORS Proxy)

The Worker is required to bypass CORS restrictions when fetching from council APIs.

```bash
cd worker

# Deploy (first time will prompt for Cloudflare login)
npx wrangler deploy

# Note the worker URL (e.g., https://bins-cors-proxy.your-subdomain.workers.dev)
```

### 2. Update Worker URL in app.js

Edit `app.js` and update the `CORS_PROXY_URL`:

```javascript
const CORS_PROXY_URL = 'https://bins-cors-proxy.your-subdomain.workers.dev';
```

### 3. Deploy Static Site to Cloudflare Pages

**Option A: GitHub Integration (Recommended - Automatic Deployments)**

This is the easiest way - every git push automatically deploys your site!

1. **Push your code to GitHub:**
   ```bash
   git add .
   git commit -m "Initial commit"
   git push
   ```

2. **Connect Cloudflare Pages to GitHub:**
   - Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → Pages
   - Click "Create a project" → "Connect to Git"
   - Authorize Cloudflare to access your GitHub account
   - Select your `bins` repository

3. **Configure build settings:**
   ```
   Project name: uk-bin-lookup (or whatever you prefer)
   Production branch: main
   Build command: npm install && npm run convert-yaml
   Build output directory: bins-website
   Root directory: (leave blank - use repository root)
   ```

4. **Click "Save and Deploy"**

**That's it! From now on:**
- Every push to `main` → automatic production deployment
- Every push to other branches → automatic preview deployment
- View build logs and deployment history in Cloudflare dashboard
- Rollback to previous versions with one click

Your site will be live at: `https://uk-bin-lookup.pages.dev` (or your custom name)

**Option B: Direct Upload (Simplest)**

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → Pages
2. Create New Project → Upload assets
3. Drag and drop the `bins-website` folder
4. Deploy!

Your site will be live at: `https://your-project.pages.dev`

### 4. Optional: Custom Domain

In Cloudflare Pages:
1. Go to your project → Custom domains
2. Add your domain (e.g., `bins.yourdomain.com`)
3. Follow DNS setup instructions

## How It Works

1. **User enters postcode** → Client fetches addresses via UPRN lookup API (CORS-enabled)
2. **User selects address** → Client identifies council via GOV.UK API (CORS-enabled)
3. **Client builds request** → Uses council config from `councils-data.json`
4. **Request sent to Worker** → Worker proxies request to council API
5. **Results displayed** → Bin collection data shown to user

## Supported Councils

- **185** councils with single API endpoint
- **79** councils with ID-based lookup
- **42** councils with token-based authentication

See `about.html` for more details.

## Development Scripts

| Command | Description |
|---------|-------------|
| `npm run convert-yaml` | Convert YAML configs to JSON |
| `npm run check` | Run Biome linter and auto-fix |
| `npm run format` | Format code with Biome |
| `npm run lint` | Lint code (no auto-fix) |

## Technology Stack

- **HTML/CSS/JavaScript** - No framework dependencies
- **[Pico CSS](https://picocss.com)** - Minimal, elegant CSS framework
- **[Biome](https://biomejs.dev)** - Fast linter and formatter
- **[Cloudflare Pages](https://pages.cloudflare.com)** - Static site hosting
- **[Cloudflare Workers](https://workers.cloudflare.com)** - CORS proxy

## Architecture Decisions

- ✅ No build tools (plain HTML/CSS/JS)
- ✅ No JavaScript frameworks (vanilla JS)
- ✅ No TypeScript (as requested)
- ✅ Client-side only (no backend needed)
- ✅ YAML configs converted to single JSON file
- ✅ Input + datalist for auto-filtering address dropdown

## Contributing

1. Add new council YAML files to `../src/councils/`
2. Run `npm run convert-yaml` to regenerate JSON
3. Test locally
4. Submit PR

## License

MIT

## Credits

Built on council configuration data extracted as part of an open-source effort to make UK bin collection data more accessible.
