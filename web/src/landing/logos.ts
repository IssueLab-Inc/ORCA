/**
 * The logos of the formats and tools ORCA reads and writes, as the landing shows them (files in web/public/logos).
 * IFC and BCF are buildingSMART International's, Navisworks is Autodesk's and MCP the Model Context Protocol's; STEP
 * and PDF have no mark of their own, so these two were drawn for ORCA. They are shown only to name what ORCA works with
 * (docs/brand-assets.md, "Other people's logos").
 */
export const LOGO = {
  ifc: "/logos/ifc.png", step: "/logos/step.svg", navisworks: "/logos/navisworks.png",
  bcf: "/logos/bcf.png", pdf: "/logos/pdf.svg", mcp: "/logos/mcp.png",
} as const;
export type LogoKey = keyof typeof LOGO;

/** What ORCA reads and writes, each with its logo and which way it goes (docs/architecture/14-files-in-and-out.md). */
export const FORMATS: { key: LogoKey; name: string; what: string }[] = [
  { key: "ifc", name: "IFC", what: "Building models, in and out" },
  { key: "step", name: "STEP", what: "Machine models, in and out" },
  { key: "navisworks", name: "Navisworks", what: "Its clash reports, in" },
  { key: "bcf", name: "BCF", what: "Issues for each team, out" },
  { key: "pdf", name: "PDF", what: "The coordination report, out" },
  { key: "mcp", name: "MCP", what: "Your own agent, plugged in" },
];
