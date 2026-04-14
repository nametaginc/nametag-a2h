/**
 * OpenClaw plugin for Nametag A2H identity enrollment.
 *
 * Registers a /nametag-enroll slash command that the owner uses to enroll
 * their identity. This is intentionally a command (not a tool) — the agent
 * cannot invoke it. Enrollment is a human-initiated action.
 *
 * The MCP server (Python) provides the agent-facing tools (nametag_authorize,
 * nametag_status) and should be configured separately in OpenClaw's mcp.servers.
 */

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { execSync } from "child_process";

// Use the nametag-a2h CLI entry point installed by pipx.
// Fall back to ~/.local/bin if not on PATH.
function findCLI(): string {
  try {
    return execSync("which nametag-a2h", { encoding: "utf-8" }).trim();
  } catch {
    return process.env.HOME + "/.local/bin/nametag-a2h";
  }
}
const CLI = findCLI();

export default definePluginEntry({
  id: "nametag-a2h",
  name: "Nametag A2H",
  description:
    "Identity-verified agent approvals via Nametag and the A2H protocol",
  register(api) {
    // /nametag-enroll <phone> — owner-only enrollment command
    api.registerCommand({
      name: "nametag-enroll",
      description:
        "Enroll your identity for agent action approvals. " +
        "Usage: /nametag-enroll +15551234567",
      acceptsArgs: true,
      requireAuth: true,
      handler: async (ctx) => {
        const phone = ctx.args?.trim();
        if (!phone) {
          return {
            text:
              "Usage: /nametag-enroll <phone>\n" +
              "Example: /nametag-enroll +15551234567\n\n" +
              "This will send a verification link to your phone. " +
              "Scan your government ID to complete enrollment.",
          };
        }

        // Validate phone format (basic check)
        if (!/^\+\d{7,15}$/.test(phone)) {
          return {
            text:
              "Invalid phone number format. Use international format: +15551234567",
          };
        }

        try {
          const result = execSync(
            `"${CLI}" enroll "${phone}"`,
            {
              encoding: "utf-8",
              timeout: 120_000,
              env: process.env,
            }
          );
          return { text: result };
        } catch (err: unknown) {
          const error = err as { stderr?: string; message?: string };
          const message = error.stderr || error.message || "Unknown error";
          return { text: `Enrollment failed:\n${message}` };
        }
      },
    });

    // /nametag-status — check enrollment status
    api.registerCommand({
      name: "nametag-status",
      description: "Check your Nametag A2H enrollment status.",
      acceptsArgs: false,
      handler: async () => {
        try {
          const result = execSync(`"${CLI}" status`, {
            encoding: "utf-8",
            timeout: 10_000,
            env: process.env,
          });
          return { text: result };
        } catch (err: unknown) {
          const error = err as { stderr?: string; message?: string };
          const message = error.stderr || error.message || "Unknown error";
          return { text: `Status check failed:\n${message}` };
        }
      },
    });

    // /nametag-clear — remove enrolled identity (owner-only)
    api.registerCommand({
      name: "nametag-clear",
      description: "Remove your enrolled identity. You will need to re-enroll.",
      acceptsArgs: false,
      requireAuth: true,
      handler: async () => {
        try {
          const result = execSync(`"${CLI}" clear`, {
            encoding: "utf-8",
            timeout: 10_000,
            env: process.env,
          });
          return { text: result };
        } catch (err: unknown) {
          const error = err as { stderr?: string; message?: string };
          const message = error.stderr || error.message || "Unknown error";
          return { text: `Clear failed:\n${message}` };
        }
      },
    });
  },
});
