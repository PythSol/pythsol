import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// Light theme only (ADR-0008). Dark OS preferences still get these colors
// from src/styles/theme.css. Tokens live in web/shared-tokens/tokens.json.
export default defineConfig({
  // Hosted under one domain: https://pythsol.com serves /docs from this build.
  site: "https://www.pythsol.com",
  base: "/docs",
  trailingSlash: "never",
  integrations: [
    starlight({
      title: "PythSol",
      description: "Write Solana programs in a typed Python subset, compiled to native SBF.",
      customCss: ["./src/styles/theme.css"],
      components: {
        Header: "./src/components/Header.astro",
        SiteTitle: "./src/components/SiteTitle.astro",
      },
      expressiveCode: { themes: ["github-light"] },
      editLink: { baseUrl: "https://github.com/PythSol/pythsol/edit/main/web/docs/" },
      lastUpdated: true,
      sidebar: [
        {
          label: "Start",
          items: [
            { label: "Introduction", slug: "index" },
            { label: "Quickstart", slug: "quickstart" },
            { label: "Local playground", slug: "playground" },
          ],
        },
        {
          label: "Learn",
          items: [
            { label: "Counter", slug: "tutorial-counter" },
            { label: "Vault", slug: "tutorial-vault" },
            { label: "Escrow", slug: "tutorial-escrow" },
            { label: "Accounts", slug: "accounts" },
            { label: "Language", slug: "language" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "API", slug: "api" },
            { label: "CLI", slug: "cli" },
            { label: "Client", slug: "client" },
            { label: "Errors", slug: "errors" },
            { label: "Testing", slug: "testing" },
            { label: "Troubleshooting", slug: "troubleshooting" },
          ],
        },
        {
          label: "Project",
          items: [
            { label: "Migrate", slug: "migrate" },
            { label: "Security", slug: "security" },
            { label: "Architecture", slug: "architecture" },
            { label: "Changelog", slug: "changelog" },
            { label: "Roadmap", slug: "roadmap" },
            { label: "Contributing", slug: "contributing" },
          ],
        },
      ],
    }),
  ],
});
