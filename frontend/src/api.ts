import { z } from "zod";

export type Node =
  | { kind: "text"; value: string }
  | { kind: "problem"; message: string }
  | Container;
export type Container = { kind: "card" | "list" | "list_item" | "row" | "col"; children: Node[] };
const nodeSchema: z.ZodType<Node> = z.lazy(() => z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("text"), value: z.string() }).strict(),
  z.object({ kind: z.literal("problem"), message: z.string() }).strict(),
  z.object({ kind: z.enum(["card", "list", "list_item", "row", "col"]), children: z.array(nodeSchema).max(100) }).strict(),
]));
const cardSchema: z.ZodType<Container> = z.object({
  kind: z.enum(["card", "list"]), children: z.array(nodeSchema).max(100),
}).strict();
const issueSchema = z.object({
  code: z.string(), path: z.string(), severity: z.enum(["warning", "error"]), message: z.string(),
}).strict();
const resultSchema = z.discriminatedUnion("status", [
  z.object({ status: z.literal("valid"), preview: cardSchema, issues: z.array(issueSchema).length(0) }).strict(),
  z.object({ status: z.literal("partial"), preview: cardSchema, issues: z.array(issueSchema).min(1).max(100) }).strict(),
  z.object({ status: z.literal("invalid"), preview: z.null(), issues: z.array(issueSchema).min(1).max(100) }).strict(),
]);

export type Card = Container;
export type ValidationResult = z.infer<typeof resultSchema>;

export async function validatePayload(source: string): Promise<ValidationResult> {
  const response: Response = await fetch("/api/payloads/validate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }),
  });
  if (!response.ok) throw new Error(`Validation request failed (${response.status}).`);
  const payload: unknown = await response.json();
  return resultSchema.parse(payload);
}
