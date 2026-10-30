import { z } from "zod";

export type Node =
  | { kind: "text" | "title" | "caption"; value: string; weight?: "normal" | "medium" | "semibold" | "bold" }
  | { kind: "badge"; label: string }
  | { kind: "divider" }
  | { kind: "problem"; message: string }
  | Container;
export type Container = { kind: "card" | "list" | "list_item" | "row" | "col"; children: Node[]; gap?: number };
const nodeSchema: z.ZodType<Node> = z.lazy(() => z.discriminatedUnion("kind", [
  z.object({ kind: z.enum(["text", "title", "caption"]), value: z.string(), weight: z.enum(["normal", "medium", "semibold", "bold"]).optional() }).strict(),
  z.object({ kind: z.literal("badge"), label: z.string() }).strict(),
  z.object({ kind: z.literal("divider") }).strict(),
  z.object({ kind: z.literal("problem"), message: z.string() }).strict(),
  z.object({ kind: z.enum(["card", "list", "list_item", "row", "col"]), children: z.array(nodeSchema).max(100), gap: z.number().int().min(0).max(8).optional() }).strict(),
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

const menuSchema = z.object({
  revision: z.number().int().positive(),
  items: z.array(z.object({
    id: z.string(), position: z.number().int().positive(),
    name: z.object({ en: z.string(), ar: z.string() }).strict(),
    price_minor: z.number().int().nonnegative(), currency: z.literal("AED"), available: z.boolean(),
  }).strict()),
}).strict();
export type Menu = z.infer<typeof menuSchema>;

export async function fetchMenu(): Promise<Menu> {
  const response: Response = await fetch("/api/menu");
  if (!response.ok) throw new Error(`Menu request failed (${response.status}).`);
  const payload: unknown = await response.json();
  return menuSchema.parse(payload);
}

export async function sellOutItem(itemId: string): Promise<Menu> {
  const response: Response = await fetch(`/api/demo/menu/${encodeURIComponent(itemId)}/sell-out`, {
    method: "POST", headers: { "X-Demo-Action": "sell-out" },
  });
  if (!response.ok) throw new Error(`Sell-out request failed (${response.status}).`);
  const payload: unknown = await response.json();
  return menuSchema.parse(payload);
}

export async function restockItem(itemId: string): Promise<Menu> {
  const response: Response = await fetch(`/api/demo/menu/${encodeURIComponent(itemId)}/restock`, {
    method: "POST", headers: { "X-Demo-Action": "restock" },
  });
  if (!response.ok) throw new Error(`Restock request failed (${response.status}).`);
  const payload: unknown = await response.json();
  return menuSchema.parse(payload);
}

const cartSchema = z.object({
  items: z.array(z.object({ id: z.string(), name_en: z.string(), name_ar: z.string(), quantity: z.number().int().min(1).max(99), price_minor: z.number().int().nonnegative(), available: z.boolean() }).strict()),
  total_minor: z.number().int().nonnegative(), currency: z.literal("AED"), can_checkout: z.boolean(), revision: z.string().length(64),
}).strict();
export type Cart = z.infer<typeof cartSchema>;
let sessionRequest: Promise<Cart> | null = null;
export function startSession(): Promise<Cart> {
  if (sessionRequest === null) {
    sessionRequest = fetch("/api/session", { method: "POST", headers: { "X-Demo-Action": "session" } })
      .then(async (response: Response): Promise<Cart> => {
        if (!response.ok) throw new Error(`Session request failed (${response.status}).`);
        const payload: unknown = await response.json();
        return cartSchema.parse(payload);
      }).finally(() => { sessionRequest = null; });
  }
  return sessionRequest;
}
export async function fetchCart(): Promise<Cart> {
  const response: Response = await fetch("/api/cart");
  if (!response.ok) throw new Error(`Cart request failed (${response.status}).`);
  const payload: unknown = await response.json();
  return cartSchema.parse(payload);
}
export async function updateCart(itemId: string, quantity: number, actionId: string): Promise<Cart> {
  const response: Response = await fetch("/api/cart/quantity", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "cart" },
    body: JSON.stringify({ item_id: itemId, quantity, action_id: actionId }),
  });
  if (!response.ok) {
    const payload: unknown = await response.json();
    const error = z.object({ message: z.string() }).safeParse(payload);
    throw new Error(error.success ? error.data.message : `Cart request failed (${response.status}).`);
  }
  const payload: unknown = await response.json();
  return cartSchema.parse(payload);
}

const orderSchema = z.object({
  order_id: z.string(), status: z.literal("confirmed"),
  items: cartSchema.shape.items, total_minor: z.number().int().nonnegative(), currency: z.literal("AED"),
}).strict();
export type Order = z.infer<typeof orderSchema>;
export async function confirmOrder(actionId: string, cartRevision: string): Promise<Order> {
  const response: Response = await fetch("/api/orders/confirm", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "confirm" },
    body: JSON.stringify({ action_id: actionId, cart_revision: cartRevision }),
  });
  if (!response.ok) {
    const payload: unknown = await response.json();
    const error = z.object({ message: z.string() }).safeParse(payload);
    throw new Error(error.success ? error.data.message : `Confirmation failed (${response.status}).`);
  }
  const payload: unknown = await response.json();
  return orderSchema.parse(payload);
}

const snapshotSchema = z.object({ menu: menuSchema, cart: cartSchema }).strict();
export type Snapshot = z.infer<typeof snapshotSchema>;
export function parseSnapshot(source: string): Snapshot {
  const payload: unknown = JSON.parse(source);
  return snapshotSchema.parse(payload);
}

const chatReplySchema = z.object({
  text: z.string().min(1).max(1200),
  suggestion: z.object({ item_id: z.string(), quantity: z.number().int().min(0).max(99) }).strict().nullable(),
  menu_revision: z.number().int().positive(), cart_revision: z.string().length(64),
  widget: cardSchema.nullable(), locale: z.enum(["en", "ar"]),
}).strict();
export type ChatReply = z.infer<typeof chatReplySchema>;
export async function sendChat(text: string, menuRevision: number, messageId: string, locale: "en" | "ar"): Promise<ChatReply> {
  const response: Response = await fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "chat" },
    body: JSON.stringify({ text, menu_revision: menuRevision, client_message_id: messageId, locale }),
  });
  if (!response.ok) {
    const payload: unknown = await response.json();
    const error = z.object({ message: z.string() }).safeParse(payload);
    throw new Error(error.success ? error.data.message : `Chat request failed (${response.status}).`);
  }
  const payload: unknown = await response.json();
  return chatReplySchema.parse(payload);
}
