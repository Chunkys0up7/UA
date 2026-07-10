/**
 * Root layout — wraps every page in the <CopilotProvider />.
 *
 * The provider connects to /api/copilotkit (the runtime route handler)
 * which in turn calls the FastAPI backend. We import the CopilotKit
 * stylesheet here so the chat UI is themed consistently across pages.
 *
 * Spec: docs/classes/RootLayout.md
 */
import type { Metadata } from "next";
import "@copilotkit/react-ui/styles.css";
import "./globals.css";
import { CopilotProvider } from "@/components/CopilotProvider";

export const metadata: Metadata = {
  title: "CopilotKit Kickstarter",
  description: "A clean, spec-driven scaffold for CopilotKit-powered apps.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <CopilotProvider>{children}</CopilotProvider>
      </body>
    </html>
  );
}
