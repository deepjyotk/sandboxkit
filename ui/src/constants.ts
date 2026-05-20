/** Playground form options. Kept in one place so the playground page stays declarative. */

export type TemplateValue = "sandboxkit-py-template" | "sandbox-js-template";
export type Lang = "python" | "javascript";

export type TemplateOption = {
  value: TemplateValue;
  label: string;
  lang: Lang;
  defaultCode: string;
};

export const TEMPLATES: TemplateOption[] = [
  {
    value: "sandboxkit-py-template",
    label: "Python (FastAPI)",
    lang: "python",
    defaultCode: 'print("hello from playground")\n',
  },
  {
    value: "sandbox-js-template",
    label: "Node.js (TS/JS)",
    lang: "javascript",
    defaultCode:
      'const msg: string = "hello from playground";\nconsole.log(msg);\n',
  },
];

/** Mirrors backend simulate_vault_service.VAULT. Backend has no GET /secrets endpoint. */
export const SECRETS = ["SECRET_KEY1", "SECRET_KEY2"] as const;

export type SelectOption = { value: string; label: string };

export const CPU_LIMITS: SelectOption[] = [
  { value: "", label: "(default 500m)" },
  { value: "100m", label: "100m (0.1 core)" },
  { value: "250m", label: "250m (0.25 core)" },
  { value: "500m", label: "500m (0.5 core)" },
  { value: "1", label: "1 core" },
];

export const MEMORY_LIMITS: SelectOption[] = [
  { value: "", label: "(default 256Mi)" },
  { value: "64Mi", label: "64Mi" },
  { value: "128Mi", label: "128Mi" },
  { value: "256Mi", label: "256Mi" },
  { value: "512Mi", label: "512Mi" },
  { value: "1Gi", label: "1Gi" },
];
