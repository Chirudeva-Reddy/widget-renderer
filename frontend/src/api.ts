import { z } from "zod";

export type Node =
  | { kind: "text" | "title" | "caption"; value: string; weight?: "normal" | "medium" | "semibold" | "bold" }
  | { kind: "badge"; label: string }
  | { kind: "divider" }
  | { kind: "spacer" }
  | { kind: "table"; rows: TableRow[] }
  | ChartNode
  | ControlNode
  | { kind: "problem"; message: string }
  | Container;
export type ControlNode =
  | { kind: "button"; label: string }
  | { kind: "input"; name: string; value: string; placeholder: string; required: boolean; disabled: boolean }
  | { kind: "select"; name: string; value: string; placeholder: string; disabled: boolean; options: { value: string; label: string; disabled: boolean }[] };
export type ChartNode = { kind: "chart"; points: { label: string; values: number[] }[]; series: { type: "bar" | "line"; label: string; color?: "blue" | "purple" | "orange" | "green" | "red" | "yellow" | "pink" }[]; show_y_axis: boolean; show_legend: boolean };
export type TableRow = { header: boolean; cells: TableCell[] };
export type TableCell = { children: Node[]; align?: "start" | "center" | "end" };
export type Container = { kind: "card" | "list" | "list_item" | "row" | "col" | "form" | "box"; children: Node[]; gap?: number; key?: string; direction?: "row" | "col"; align?: "start" | "center" | "end" | "baseline" | "stretch"; justify?: "start" | "center" | "end" | "between" | "around" | "evenly" | "stretch"; padding?: number; flex?: number };
const nodeSchema: z.ZodType<Node> = z.lazy(() => z.discriminatedUnion("kind", [
  z.object({ kind: z.enum(["text", "title", "caption"]), value: z.string(), weight: z.enum(["normal", "medium", "semibold", "bold"]).optional() }).strict(),
  z.object({ kind: z.literal("button"), label: z.string().max(256) }).strict(),
  z.object({ kind: z.literal("input"), name: z.string().max(64), value: z.string().max(256), placeholder: z.string().max(256), required: z.boolean(), disabled: z.boolean() }).strict(),
  z.object({ kind: z.literal("select"), name: z.string().max(64), value: z.string().max(256), placeholder: z.string().max(256), disabled: z.boolean(), options: z.array(z.object({ value: z.string().max(256), label: z.string().max(256), disabled: z.boolean() }).strict()).min(1).max(100) }).strict(),
  z.object({ kind: z.literal("badge"), label: z.string() }).strict(),
  z.object({ kind: z.literal("divider") }).strict(),
  z.object({ kind: z.literal("spacer") }).strict(),
  z.object({ kind: z.literal("chart"), points: z.array(z.object({ label: z.string(), values: z.array(z.number().finite()).min(1).max(4) }).strict()).min(1).max(200), series: z.array(z.object({ type: z.enum(["bar", "line"]), label: z.string(), color: z.enum(["blue", "purple", "orange", "green", "red", "yellow", "pink"]).optional() }).strict()).min(1).max(4), show_y_axis: z.boolean(), show_legend: z.boolean() }).strict().refine((chart) => chart.points.every((point) => point.values.length === chart.series.length)),
  z.object({ kind: z.literal("table"), rows: z.array(z.object({
    header: z.boolean(), cells: z.array(z.object({ children: z.array(nodeSchema).max(100), align: z.enum(["start", "center", "end"]).optional() }).strict()).max(20),
  }).strict()).max(100) }).strict(),
  z.object({ kind: z.literal("problem"), message: z.string() }).strict(),
  z.object({ kind: z.enum(["card", "list", "list_item", "row", "col", "form", "box"]), children: z.array(nodeSchema).max(100), gap: z.number().int().min(0).max(8).optional(), key: z.string().max(128).optional(), direction: z.enum(["row", "col"]).optional(), align: z.enum(["start", "center", "end", "baseline", "stretch"]).optional(), justify: z.enum(["start", "center", "end", "between", "around", "evenly", "stretch"]).optional(), padding: z.number().int().min(0).max(8).optional(), flex: z.number().int().min(0).max(8).optional() }).strict(),
]));
const cardSchema: z.ZodType<Container> = z.object({
  kind: z.enum(["card", "list"]), children: z.array(nodeSchema).max(100), key: z.string().max(128).optional(),
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
export async function updateWidgetCart(widgetId: string, revision: number, actionId: string, itemId: string, position: number, quantity: number, cartRevision: string): Promise<Cart> {
  const response: Response = await fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-action" }, body: JSON.stringify({ widget_id: widgetId, revision, action_id: actionId, type: "cart.set_quantity", payload: { item_id: itemId, position, quantity, cart_revision: cartRevision } }) });
  const payload: unknown = await response.json();
  if (!response.ok) {
    const error = z.object({ message: z.string() }).safeParse(payload);
    throw new Error(error.success ? error.data.message : `Widget action failed (${response.status}).`);
  }
  return cartSchema.parse(payload);
}

export async function updateCart(itemId: string, quantity: number, actionId: string, cartRevision: string): Promise<Cart> {
  const response: Response = await fetch("/api/cart/quantity", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "cart" },
    body: JSON.stringify({ item_id: itemId, quantity, action_id: actionId, cart_revision: cartRevision }),
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
export class ConfirmationConflict extends Error {}

const checkoutViewSchema = z.object({ kind: z.literal("widget"), role: z.literal("confirmation"), actions: z.array(z.object({ type: z.enum(["order.confirm", "order.edit"]), enabled: z.boolean() }).strict()).length(2), payload: z.object({ en: cardSchema, ar: cardSchema }).strict(), cart_revision: z.string().regex(/^[a-f0-9]{64}$/), widget_id: z.string().min(1).max(128), revision: z.number().int().positive(), cart: cartSchema }).strict().refine((view) => view.cart_revision === view.cart.revision);
export type CheckoutView = z.infer<typeof checkoutViewSchema>;
export async function startWidgetCheckout(widgetId: string, revision: number, actionId: string, cartRevision: string): Promise<CheckoutView> {
  const response: Response = await fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-action" }, body: JSON.stringify({ widget_id: widgetId, revision, action_id: actionId, type: "checkout.start", payload: { cart_revision: cartRevision } }) });
  const payload: unknown = await response.json();
  if (!response.ok) { const error = z.object({ message: z.string() }).safeParse(payload); throw new Error(error.success ? error.data.message : `Checkout failed (${response.status}).`); }
  return checkoutViewSchema.parse(payload);
}

export async function editWidgetOrder(widgetId: string, revision: number, actionId: string, cartRevision: string): Promise<void> {
  const response: Response = await fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-action" }, body: JSON.stringify({ widget_id: widgetId, revision, action_id: actionId, type: "order.edit", payload: { cart_revision: cartRevision } }) });
  const payload: unknown = await response.json();
  if (!response.ok) { const error = z.object({ message: z.string() }).safeParse(payload); throw new Error(error.success ? error.data.message : `Edit failed (${response.status}).`); }
  z.object({ edited: z.literal(true) }).strict().parse(payload);
}

export async function confirmWidgetOrder(widgetId: string, revision: number, actionId: string, cartRevision: string): Promise<Order> {
  const response: Response = await fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-action" }, body: JSON.stringify({ widget_id: widgetId, revision, action_id: actionId, type: "order.confirm", payload: { cart_revision: cartRevision } }) });
  const payload: unknown = await response.json();
  if (!response.ok) { const error = z.object({ message: z.string() }).safeParse(payload); const message: string = error.success ? error.data.message : `Confirmation failed (${response.status}).`; if (response.status === 409) throw new ConfirmationConflict(message); throw new Error(message); }
  return orderSchema.parse(payload);
}

export async function confirmOrder(actionId: string, cartRevision: string): Promise<Order> {
  const response: Response = await fetch("/api/orders/confirm", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "confirm" },
    body: JSON.stringify({ action_id: actionId, cart_revision: cartRevision }),
  });
  if (!response.ok) {
    const payload: unknown = await response.json();
    const error = z.object({ message: z.string() }).safeParse(payload);
    const message: string = error.success ? error.data.message : `Confirmation failed (${response.status}).`;
    if (response.status === 409) throw new ConfirmationConflict(message);
    throw new Error(message);
  }
  const payload: unknown = await response.json();
  return orderSchema.parse(payload);
}

const widgetSchema = z.object({ kind: z.literal("widget"), actions: z.object({ quantities: z.array(z.object({ item_id: z.string(), position: z.number().int().positive(), minimum: z.number().int().nonnegative(), maximum: z.number().int().min(0).max(99) }).strict()), checkout: z.boolean() }).strict(), widget_id: z.string().min(1).max(128), revision: z.number().int().positive(), locale: z.enum(["en", "ar"]), payload: cardSchema, menu_view_id: z.string().min(1).max(128), cart_revision: z.string().length(64), menu: menuSchema, cart: cartSchema }).strict();
export type WidgetEnvelope = z.infer<typeof widgetSchema>;
export type WidgetView = { widget_id: string; revision: number };
export async function acknowledgeWidget(widget: WidgetEnvelope): Promise<void> {
  const response: Response = await fetch(`/api/widgets/${encodeURIComponent(widget.widget_id)}/rendered`, { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-rendered" }, body: JSON.stringify({ revision: widget.revision }) });
  if (!response.ok) throw new Error(`Widget acknowledgement failed (${response.status}).`);
  widgetSchema.parse(await response.json() as unknown);
}
export async function acknowledgeConfirmation(view: CheckoutView, locale: "en" | "ar"): Promise<void> {
  const response: Response = await fetch(`/api/widgets/${encodeURIComponent(view.widget_id)}/confirmation-rendered`, { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-rendered" }, body: JSON.stringify({ revision: view.revision, locale }) });
  if (!response.ok) throw new Error(`Confirmation acknowledgement failed (${response.status}). Review your cart again.`);
  checkoutViewSchema.parse(await response.json() as unknown);
}
const snapshotSchema = z.object({ state_revision: z.number().int().positive(), widgets: z.object({ en: widgetSchema, ar: widgetSchema }).strict(), menu: menuSchema, cart: cartSchema, menu_widgets: z.object({ en: cardSchema, ar: cardSchema }).strict(), menu_view_ids: z.object({ en: z.string().min(1).max(128), ar: z.string().min(1).max(128) }).strict() }).strict();
export type Snapshot = z.infer<typeof snapshotSchema>;
export function readSnapshotRevision(source: string): number {
  return z.object({ state_revision: z.number().int().positive() }).parse(JSON.parse(source) as unknown).state_revision;
}
export async function fetchState(): Promise<Snapshot> {
  const response: Response = await fetch("/api/state", { cache: "no-store" });
  if (!response.ok) throw new Error(`State synchronization failed (${response.status}). Retry Resync.`);
  return snapshotSchema.parse(await response.json() as unknown);
}
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
export type ChatStreamEvent = { type: "card"; text: string | null } | { type: "component"; index: number; node: Node };
const streamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("card"), text: z.string().max(1200).nullable() }).strict(),
  z.object({ type: z.literal("component"), index: z.number().int().min(0).max(99), node: nodeSchema }).strict(),
]);
export async function streamChat(text: string, menuRevision: number, messageId: string, locale: "en" | "ar", renderedViewId: string | null, widgetView: WidgetView | null, confirmationView: WidgetView | null, onEvent: (event: ChatStreamEvent) => void): Promise<ChatReply> {
  const response: Response = await fetch("/api/chat/stream", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "chat" },
    body: JSON.stringify({ text, menu_revision: menuRevision, client_message_id: messageId, locale, rendered_view_id: renderedViewId, widget_view: widgetView, confirmation_view: confirmationView }),
  });
  if (!response.ok || response.body === null) {
    const error = z.object({ message: z.string() }).safeParse(await response.json().catch(() => null));
    throw new Error(error.success ? error.data.message : `Chat request failed (${response.status}).`);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer: string = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) throw new Error("The reply was interrupted. Please try again.");
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block: string = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const type: string = /^event: (.*)$/m.exec(block)?.[1] ?? "";
      const data: unknown = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? "null");
      if (type === "final") return chatReplySchema.parse(data);
      if (type === "error") throw new Error(z.object({ message: z.string() }).parse(data).message);
      if (type === "card" || type === "component") onEvent(streamEventSchema.parse({ type, ...(data as object) }));
    }
  }
}

export async function sendChat(text: string, menuRevision: number, messageId: string, locale: "en" | "ar", renderedViewId: string | null, confirmationView: WidgetView | null): Promise<ChatReply> {
  const response: Response = await fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "chat" },
    body: JSON.stringify({ text, menu_revision: menuRevision, client_message_id: messageId, locale, rendered_view_id: renderedViewId, confirmation_view: confirmationView }),
  });
  if (!response.ok) {
    const payload: unknown = await response.json();
    const error = z.object({ message: z.string() }).safeParse(payload);
    throw new Error(error.success ? error.data.message : `Chat request failed (${response.status}).`);
  }
  const payload: unknown = await response.json();
  return chatReplySchema.parse(payload);
}
