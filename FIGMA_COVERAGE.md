# Figma screen coverage

This tracks every authoritative node from `goal-objective.md` against the local prototype.

| Figma node | Intended state                       | Local route/state                                | Implementation                   |
| ---------- | ------------------------------------ | ------------------------------------------------ | -------------------------------- |
| `12:1139`  | Marketing landing                    | `/es`                                            | `Landing`                        |
| `12:3696`  | Landing with auth dialog             | `/es?auth=login`                                 | `Landing` + `AuthModal`          |
| `12:11410` | Extracted editor component reference | project editor route                             | Shared editor/chat components    |
| `12:2552`  | Pricing                              | `/es/pricing`                                    | `Pricing`                        |
| `12:5919`  | Dashboard with command palette       | `/dashboard`                                     | `Dashboard` + `CommandPalette`   |
| `12:6723`  | Resources                            | `/dashboard/resources`                           | `Resources`                      |
| `12:10398` | Connectors                           | `/dashboard?connectors=1`                        | `Connectors`                     |
| `12:12025` | Project editor                       | `/projects/77199122-f79d-49b5-b6b4-c3d86b6565da` | `Editor`                         |
| `12:12778` | Account settings                     | `.../settings/account`                           | `SettingsPage(account)`          |
| `12:13289` | Apps and devices                     | `.../settings/apps`                              | `SettingsPage(apps)`             |
| `12:14074` | Project settings                     | `.../settings/project`                           | `SettingsPage(project)`          |
| `12:14631` | Workspace settings                   | `.../settings/workspace`                         | `SettingsPage(workspace)`        |
| `12:15867` | Billing                              | `.../settings/billing`                           | `SettingsPage(billing)`          |
| `12:16352` | Knowledge                            | `.../settings/knowledge`                         | `SettingsPage(knowledge)`        |
| `12:16924` | Skills                               | `.../settings/skills`                            | `SettingsPage(skills)`           |
| `12:17445` | MCP server settings                  | `.../settings/mcp-server`                        | `SettingsPage(mcp-server)`       |
| `12:18627` | Privacy and security                 | `.../settings/privacy-security`                  | `SettingsPage(privacy-security)` |

## Verification state

- Production build: passing (`npm run build`).
- Visual runtime checks completed for landing, auth dialog, pricing, dashboard, project editor, and the settings shell.
- Pricing now renders 3772 px with 4 plans, 8 comparison rows, 12 FAQ items, and the shared 892 px footer; its Figma frame is 3793 px tall.
- Landing includes the final creation CTA, the complete five-column footer, the original animated product scene, the pulse artwork, and the eight original template thumbnails from the public source captured by the Figma layers.
- Dashboard routes include their captured state: command palette, extended resource catalogue, connector states, and settings hierarchy.
- Exact sublayer/code extraction: pending because the authenticated Figma workspace has reached its Starter MCP call limit.
- Pixel-diff verification: pending until the remaining Figma frames can be exported at their natural size.
