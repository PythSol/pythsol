# Lighthouse

Measured on the live landing page, not a local preview:

```powershell
$env:CHROME_PATH = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
npx -y lighthouse@12 https://www.pythsol.com/ `
  --only-categories=performance,accessibility,best-practices,seo `
  --output=json --output-path=target/lighthouse2.json `
  --chrome-flags="--headless=new --no-sandbox" --quiet
```

Result (2026-11-03, Lighthouse 12.8.2, Edge 156, Windows, mobile defaults):

| Category | Score |
| --- | ---: |
| Performance | 86 |
| Accessibility | 100 |
| Best practices | 100 |
| SEO | 100 |

The first run scored 81 / 96 / 100 / 91. The two fixes were a footer
"Pyth" wordmark in yellow on white (`color-contrast`) and a missing
`robots.txt` (the app returned 404 HTML). Both are in the tree now:
`.foot-brand .po` uses `--blue-strong`, and `robots.txt` is served by the
local server and the Vercel function.

Re-run after site changes. Do not copy these numbers into another project or
claim a docs-page score from this landing-page run.
