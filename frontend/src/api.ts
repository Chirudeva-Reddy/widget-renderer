import { z } from "zod";

const dimensionSchema = z.union([z.number().int().min(0).max(1024), z.string().regex(/^(?:100|[0-9]{1,2})%$/)]);
const appearanceSchema = z.object({ locale: z.enum(["en", "ar"]).optional(), width: dimensionSchema.optional(), height: dimensionSchema.optional(), minWidth: z.number().int().min(0).max(1024).optional(), paddingInline: z.number().int().min(0).max(32).optional(), paddingBlock: z.number().int().min(0).max(32).optional(), borderWidth: z.number().int().min(0).max(8).optional(), borderColor: z.enum(["subtle", "default", "strong"]).optional(), theme: z.enum(["light", "dark"]).optional(), size: z.enum(["sm", "md", "lg", "full"]).optional(), variant: z.enum(["solid", "soft", "outline", "ghost"]).optional(), primary: z.boolean().optional(), uniform: z.boolean().optional(), block: z.boolean().optional(), flush: z.boolean().optional(), color: z.enum(["subtle", "default", "strong"]).optional(), limit: z.number().int().min(1).max(100).optional() }).strict();
export type Appearance = z.infer<typeof appearanceSchema>;

export type Node = (
  | { kind: "text" | "title" | "caption"; value: string; weight?: "normal" | "medium" | "semibold" | "bold"; color?: TextColor; size?: string; textAlign?: "start" | "center" | "end"; italic?: boolean; lineThrough?: boolean }
  | { kind: "badge"; label: string; color?: "secondary" | "success" | "danger" | "warning" | "info" | "discovery"; variant?: "solid" | "soft" | "outline" }
  | { kind: "divider" }
  | { kind: "spacer" }
  | { kind: "table"; rows: TableRow[] }
  | ChartNode
  | ControlNode
  | { kind: "problem"; message: string }
  | Container) & { appearance?: Appearance };
const textColors = ["prose", "primary", "emphasis", "secondary", "tertiary", "success", "warning", "danger"] as const;
type TextColor = typeof textColors[number];
const surfaces = ["surface", "surface-secondary", "surface-tertiary", "surface-elevated", "surface-elevated-secondary", "alpha-10", "alpha-15", "orange-400"] as const;
const radii = ["none", "2xs", "xs", "sm", "md", "lg", "xl", "2xl", "3xl", "4xl", "full"] as const;
export type ControlNode =
  | { kind: "button"; label: string; disabled?: boolean; key?: string }
  | { kind: "input"; key?: string; name: string; value: string; placeholder: string; required: boolean; disabled: boolean }
  | { kind: "select"; key?: string; name: string; value: string; placeholder: string; disabled: boolean; options: { value: string; label: string; disabled: boolean }[] };
export type ChartNode = { kind: "chart"; points: { label: string; values: number[] }[]; series: { type: "bar" | "line"; label: string; color?: "blue" | "purple" | "orange" | "green" | "red" | "yellow" | "pink" }[]; show_y_axis: boolean; show_legend: boolean };
export type TableRow = { header: boolean; cells: TableCell[] };
export type TableCell = { children: Node[]; align?: "start" | "center" | "end" };
export type Container = { appearance?: Appearance; kind: "card" | "list" | "list_item" | "row" | "col" | "form" | "box"; children: Node[]; gap?: number; key?: string; direction?: "row" | "col"; align?: "start" | "center" | "end" | "baseline" | "stretch"; justify?: "start" | "center" | "end" | "between" | "around" | "evenly" | "stretch"; padding?: number; flex?: number; background?: typeof surfaces[number]; radius?: typeof radii[number] };
const nodeSchema: z.ZodType<Node> = z.lazy(() => z.discriminatedUnion("kind", [
  z.object({ kind: z.enum(["text", "title", "caption"]), value: z.string(), weight: z.enum(["normal", "medium", "semibold", "bold"]).optional(), color: z.enum(textColors).optional(), size: z.enum(["xs", "sm", "md", "lg", "xl", "2xl", "3xl", "4xl", "5xl"]).optional(), textAlign: z.enum(["start", "center", "end"]).optional(), italic: z.boolean().optional(), lineThrough: z.boolean().optional() }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.literal("button"), disabled: z.boolean().optional(), label: z.string().max(256), key: z.string().max(128).optional() }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.literal("input"), key: z.string().max(128).optional(), name: z.string().max(64), value: z.string().max(256), placeholder: z.string().max(256), required: z.boolean(), disabled: z.boolean() }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.literal("select"), key: z.string().max(128).optional(), name: z.string().max(64), value: z.string().max(256), placeholder: z.string().max(256), disabled: z.boolean(), options: z.array(z.object({ value: z.string().max(256), label: z.string().max(256), disabled: z.boolean() }).extend({ appearance: appearanceSchema.optional() }).strict()).min(1).max(100) }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.literal("badge"), label: z.string(), color: z.enum(["secondary", "success", "danger", "warning", "info", "discovery"]).optional(), variant: z.enum(["solid", "soft", "outline"]).optional() }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.literal("divider") }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.literal("spacer") }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.literal("chart"), points: z.array(z.object({ label: z.string(), values: z.array(z.number().finite()).min(1).max(4) }).extend({ appearance: appearanceSchema.optional() }).strict()).min(1).max(200), series: z.array(z.object({ type: z.enum(["bar", "line"]), label: z.string(), color: z.enum(["blue", "purple", "orange", "green", "red", "yellow", "pink"]).optional() }).extend({ appearance: appearanceSchema.optional() }).strict()).min(1).max(4), show_y_axis: z.boolean(), show_legend: z.boolean() }).extend({ appearance: appearanceSchema.optional() }).strict().refine((chart) => chart.points.every((point) => point.values.length === chart.series.length)),
  z.object({ kind: z.literal("table"), rows: z.array(z.object({
    header: z.boolean(), cells: z.array(z.object({ children: z.array(nodeSchema).max(100), align: z.enum(["start", "center", "end"]).optional() }).extend({ appearance: appearanceSchema.optional() }).strict()).max(20),
  }).extend({ appearance: appearanceSchema.optional() }).strict()).max(100) }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.literal("problem"), message: z.string() }).extend({ appearance: appearanceSchema.optional() }).strict(),
  z.object({ kind: z.enum(["card", "list", "list_item", "row", "col", "form", "box"]), children: z.array(nodeSchema).max(100), gap: z.number().int().min(0).max(8).optional(), key: z.string().max(128).optional(), direction: z.enum(["row", "col"]).optional(), align: z.enum(["start", "center", "end", "baseline", "stretch"]).optional(), justify: z.enum(["start", "center", "end", "between", "around", "evenly", "stretch"]).optional(), padding: z.number().int().min(0).max(8).optional(), flex: z.number().int().min(0).max(8).optional(), background: z.enum(surfaces).optional(), radius: z.enum(radii).optional() }).extend({ appearance: appearanceSchema.optional() }).strict(),
]));
const cardSchema: z.ZodType<Container> = z.object({
  kind: z.enum(["card", "list"]), children: z.array(nodeSchema).max(100), key: z.string().max(128).optional(),
}).extend({ appearance: appearanceSchema.optional() }).strict();
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
export async function updateWidgetCart(widgetId: string, revision: number, actionId: string, itemId: string, position: number, quantity: number, cartRevision: string, actionType: "cart.add" | "cart.remove" | undefined): Promise<Cart> {
  const body = actionType === undefined ? { widget_id: widgetId, revision, action_id: actionId, type: "cart.set_quantity", payload: { item_id: itemId, position, quantity, cart_revision: cartRevision } } : { widget_id: widgetId, revision, action_id: actionId, type: actionType, payload: { id: itemId, position } };
  const response: Response = await fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-action" }, body: JSON.stringify(body) });
  const payload: unknown = await response.json();
  if (!response.ok) {
    const error = z.object({ message: z.string() }).safeParse(payload);
    const message: string = error.success ? error.data.message : `Widget action failed (${response.status}).`;
    if (response.status === 409) throw new WidgetActionConflict(message);
    throw new Error(message);
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
export type RenderedView = { locale: "en" | "ar"; rows: { item_id: string; position: number; sold_out: boolean; placeholder: boolean; quantity: string; draft: boolean; edit_revision: string | null; changed_revision: string | null; disabled: boolean; controls: { input: boolean; decrease: boolean; increase: boolean; apply: boolean; remove: boolean }; issues: ("invalid_quantity" | "stale_cart" | "sold_out")[] }[]; checkout_disabled: boolean };
export type WidgetView = { widget_id: string; revision: number; rendered: RenderedView };
export type ConfirmationRenderedView = { locale: "en" | "ar"; rows: { item_id: string; quantity: number; sold_out: boolean }[]; edit_disabled: boolean; confirm_disabled: boolean; issues: ("stale" | "drafts" | "sold_out" | "disconnected")[] };
export type ConfirmationWidgetView = { widget_id: string; revision: number; rendered: ConfirmationRenderedView };
export class WidgetActionConflict extends Error {}
export async function setWidgetLocale(widget: WidgetEnvelope, lang: "en" | "ar", actionId: string): Promise<void> {
  const response: Response = await fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-action" }, body: JSON.stringify({ widget_id: widget.widget_id, revision: widget.revision, action_id: actionId, type: "locale.set", payload: { lang } }) });
  const payload: unknown = await response.json();
  if (!response.ok) { const error = z.object({ message: z.string() }).safeParse(payload); const message: string = error.success ? error.data.message : `Language change failed (${response.status}).`; if (response.status === 409) throw new WidgetActionConflict(message); throw new Error(message); }
  z.object({ lang: z.literal(lang) }).strict().parse(payload);
}
export async function acknowledgeWidget(widget: WidgetEnvelope, rendered: RenderedView): Promise<void> {
  const response: Response = await fetch(`/api/widgets/${encodeURIComponent(widget.widget_id)}/rendered`, { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-rendered" }, body: JSON.stringify({ revision: widget.revision, rendered }) });
  if (!response.ok) throw new Error(`Widget acknowledgement failed (${response.status}).`);
  widgetSchema.parse(await response.json() as unknown);
}
export async function acknowledgeConfirmation(view: CheckoutView, rendered: ConfirmationRenderedView): Promise<void> {
  const response: Response = await fetch(`/api/widgets/${encodeURIComponent(view.widget_id)}/confirmation-rendered`, { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-rendered" }, body: JSON.stringify({ revision: view.revision, locale: rendered.locale, rendered }) });
  if (!response.ok) throw new Error(`Confirmation acknowledgement failed (${response.status}). Review your cart again.`);
  checkoutViewSchema.parse(await response.json() as unknown);
}
const updateSchema = z.object({ kind: z.literal("widget_update"), message_id: z.string().min(1).max(128), widget_id: z.string().min(1).max(128), revision: z.number().int().positive(), payload: z.object({ type: z.literal("ListView") }).passthrough() }).strict();
const snapshotSchema = z.object({ state_revision: z.number().int().positive(), widgets: z.object({ en: widgetSchema, ar: widgetSchema }).strict(), menu: menuSchema, cart: cartSchema, menu_widgets: z.object({ en: cardSchema, ar: cardSchema }).strict(), menu_view_ids: z.object({ en: z.string().min(1).max(128), ar: z.string().min(1).max(128) }).strict(), updates: z.array(updateSchema).length(2) }).strict().refine((snapshot) => (["en", "ar"] as const).every((locale, index) => {
  const widget = snapshot.widgets[locale];
  const update = snapshot.updates[index];
  return widget.locale === locale && update.widget_id === widget.widget_id && update.message_id === widget.widget_id && update.revision === widget.revision && widget.menu_view_id === snapshot.menu_view_ids[locale] && widget.cart_revision === snapshot.cart.revision && JSON.stringify(widget.menu) === JSON.stringify(snapshot.menu) && JSON.stringify(widget.cart) === JSON.stringify(snapshot.cart) && JSON.stringify(widget.payload) === JSON.stringify(snapshot.menu_widgets[locale]);
}), { message: "Snapshot widget identities or data do not match." });
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
export async function validateSnapshot(snapshot: Snapshot): Promise<void> {
  const results: ValidationResult[] = await Promise.all(snapshot.updates.map((update) => validatePayload(JSON.stringify(update.payload))));
  for (const [index, locale] of (["en", "ar"] as const).entries()) {
    const result = results[index];
    if (result.status !== "valid" || JSON.stringify(result.preview) !== JSON.stringify(snapshot.widgets[locale].payload)) throw new Error("A live widget update failed validation. Resync to recover.");
  }
}

const messageSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("text"), message_id: z.string().min(1).max(128), widget_id: z.null(), revision: z.null(), payload: z.object({ text: z.string().max(1200) }).strict() }).strict(),
  z.object({ kind: z.enum(["widget", "widget_update"]), message_id: z.string().min(1).max(128), widget_id: z.string().min(1).max(128), revision: z.number().int().positive(), payload: z.object({ type: z.enum(["Card", "ListView"]) }).passthrough() }).strict(),
]);
const genericWidgetSchema = z.object({ widget_id: z.string().min(1).max(128), revision: z.number().int().positive(), menu_revision: z.number().int().positive(), cart_revision: z.string().length(64), bindings: z.array(z.object({ key: z.string().min(1).max(128), type: z.enum(["cart.add", "cart.remove", "cart.set_quantity"]), quantities: z.array(z.number().int().min(0).max(99)).max(100).optional(), item_id: z.string().min(1).max(128), position: z.number().int().positive(), enabled: z.boolean(), label: z.string().min(1).max(256) }).strict()).max(100) }).strict();
export type GenericWidget = z.infer<typeof genericWidgetSchema>;
const genericStateSchema = z.array(z.object({ widget: genericWidgetSchema, preview: cardSchema, payload: z.object({ type: z.literal("Card") }).passthrough() }).strict()).max(100);
export type GenericState = z.infer<typeof genericStateSchema>[number];
export async function fetchGenericState(): Promise<GenericState[]> {
  const ids: string[] = Array.from(document.querySelectorAll<HTMLElement>("[data-generic-widget]")).map((element) => element.dataset.genericWidget!);
  if (ids.length === 0) return [];
  const response: Response = await fetch("/api/widgets/generic-state", { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-rendered" }, body: JSON.stringify({ widget_ids: ids }) });
  const payload: unknown = await response.json();
  if (!response.ok) { const error = z.object({ message: z.string() }).safeParse(payload); throw new Error(error.success ? error.data.message : `Generic synchronization failed (${response.status}).`); }
  const states: GenericState[] = genericStateSchema.parse(payload);
  if (states.length !== ids.length || states.some((state, index) => state.widget.widget_id !== ids[index])) throw new Error("The synchronized generic widget identities do not match.");
  await Promise.all(states.map(async (state): Promise<void> => { const result: ValidationResult = await validatePayload(JSON.stringify(state.payload)); if (result.status !== "valid" || JSON.stringify(result.preview) !== JSON.stringify(state.preview)) throw new Error("A synchronized generic widget failed validation."); }));
  return states;
}

const chatReplySchema = z.object({
  message_id: z.string().min(1).max(128),
  text: z.string().max(1200),
  suggestion: z.object({ item_id: z.string(), quantity: z.number().int().min(0).max(99) }).strict().nullable(),
  suggestions: z.array(z.object({ item_id: z.string(), quantity: z.number().int().min(0).max(99) }).strict()).max(4),
  menu_revision: z.number().int().positive(), cart_revision: z.string().length(64),
  widget: cardSchema.nullable(), locale: z.enum(["en", "ar"]),
  messages: z.array(messageSchema).min(1).max(4), widget_previews: z.array(cardSchema).max(3), widget_authors: z.array(z.enum(["backend", "model", "unknown"])).max(3), widget_controls: z.array(genericWidgetSchema.nullable()).max(3),
  proposed_actions: z.array(z.object({ type: z.enum(["locale.set", "checkout.start"]), lang: z.enum(["en", "ar"]).nullable() }).strict()).max(4),
  widget_author: z.enum(["backend", "model", "unknown"]).nullable(), warnings: z.array(z.literal("price_reconciled")),
}).strict().refine((reply) => reply.widget_previews.length === reply.widget_authors.length && reply.widget_previews.length === reply.widget_controls.length, { message: "Widget metadata does not match the returned widgets." });
export type ChatReply = z.infer<typeof chatReplySchema>;
export type ChatStreamEvent = { type: "card"; text: string | null } | { type: "component"; index: number; node: Node };
const streamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("card"), text: z.string().max(1200).nullable() }).strict(),
  z.object({ type: z.literal("component"), index: z.number().int().min(0).max(99), node: nodeSchema }).strict(),
]);
const genericReferenceSchema = z.object({ widget_id: z.string().min(1).max(128), revision: z.number().int().positive(), rendered: z.object({ locale: z.enum(["en", "ar"]), fields: z.array(z.object({ index: z.number().int().min(0).max(999), name: z.string().min(1).max(64), value: z.string().max(256), disabled: z.boolean(), unavailable: z.boolean() }).strict()).max(100) }).strict() }).strict();
type GenericReference = z.infer<typeof genericReferenceSchema>;

async function acknowledgeDisplayedGenericWidgets(): Promise<GenericReference[]> {
  const references: GenericReference[] = Array.from(document.querySelectorAll<HTMLElement>("[data-generic-widget]")).map((element) => {
    const locale: string | undefined = element.firstElementChild?.closest<HTMLElement>("[lang]")?.lang;
    if (locale !== "en" && locale !== "ar") throw new Error("The displayed generic widget has no supported language.");
    return genericReferenceSchema.parse({ widget_id: element.dataset.genericWidget, revision: Number(element.dataset.revision), rendered: { locale, fields: Array.from(element.querySelectorAll<HTMLInputElement | HTMLSelectElement>("input[name], select[name]")).map((field, index) => ({ index, name: field.name, value: field.value, disabled: field.matches(":disabled"), unavailable: field instanceof HTMLSelectElement && field.value !== "" && !Array.from(field.options).some((option) => option.value === field.value && !option.disabled) })) } });
  });
  if (references.length > 100) throw new Error("Too many displayed generic widgets to acknowledge.");
  await Promise.all(references.map(async (reference): Promise<void> => {
    const response: Response = await fetch(`/api/widgets/${encodeURIComponent(reference.widget_id)}/generic-rendered`, { method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "widget-rendered" }, body: JSON.stringify(reference) });
    const payload: unknown = await response.json();
    if (!response.ok) { const error = z.object({ message: z.string() }).safeParse(payload); const message: string = error.success ? error.data.message : `Generic draft acknowledgement failed (${response.status}).`; if (response.status === 409) throw new WidgetActionConflict(message); throw new Error(message); }
    const acknowledged: GenericReference = genericReferenceSchema.parse(payload);
    if (JSON.stringify(acknowledged) !== JSON.stringify(reference)) throw new Error("The generic draft acknowledgement does not match the displayed widget.");
  }));
  return references;
}

export async function streamChat(text: string, menuRevision: number, messageId: string, locale: "en" | "ar", renderedViewId: string | null, widgetView: WidgetView | null, confirmationView: ConfirmationWidgetView | null, onEvent: (event: ChatStreamEvent) => void): Promise<ChatReply> {
  const genericViews: GenericReference[] = await acknowledgeDisplayedGenericWidgets();
  const response: Response = await fetch("/api/chat/stream", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "chat" },
    body: JSON.stringify({ text, menu_revision: menuRevision, client_message_id: messageId, locale, generic_views: genericViews, rendered_view_id: renderedViewId, widget_view: widgetView, confirmation_view: confirmationView }),
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

export async function sendChat(text: string, menuRevision: number, messageId: string, locale: "en" | "ar", renderedViewId: string | null, confirmationView: ConfirmationWidgetView | null): Promise<ChatReply> {
  const genericViews: GenericReference[] = await acknowledgeDisplayedGenericWidgets();
  const response: Response = await fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Action": "chat" },
    body: JSON.stringify({ text, menu_revision: menuRevision, client_message_id: messageId, locale, generic_views: genericViews, rendered_view_id: renderedViewId, confirmation_view: confirmationView }),
  });
  if (!response.ok) {
    const payload: unknown = await response.json();
    const error = z.object({ message: z.string() }).safeParse(payload);
    throw new Error(error.success ? error.data.message : `Chat request failed (${response.status}).`);
  }
  const payload: unknown = await response.json();
  return chatReplySchema.parse(payload);
}
