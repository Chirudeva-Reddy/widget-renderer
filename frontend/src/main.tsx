import { Component, StrictMode, createContext, useContext, useEffect, useRef, useState } from "react";
import type { CSSProperties, FormEvent, ReactElement, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { z } from "zod";
import { acknowledgeConfirmation, acknowledgeWidget, ConfirmationConflict, WidgetActionConflict, confirmOrder, confirmWidgetOrder, editWidgetOrder, fetchCart, fetchMenu, fetchState, fetchGenericState, parseSnapshot, readSnapshotRevision, restockItem, sellOutItem, setWidgetLocale, startSession, startWidgetCheckout, streamChat, updateCart, updateWidgetCart, validatePayload, validateSnapshot } from "./api";
import type { Card, Cart, ChatReply, Menu, Node, Order, Snapshot, ValidationResult, WidgetEnvelope, CheckoutView, RenderedView, ConfirmationRenderedView, GenericWidget, GenericState } from "./api";
import { Chart } from "./Chart";
import { ConfirmationRecovery, OrderReceipt, OrderReview } from "./CheckoutWidget";
import { OrderingMenu } from "./OrderingMenu";
import type { CartChange, QuantityEdit } from "./OrderingMenu";
import { PreviewControl, PreviewForm, WidgetDraftProvider } from "./PreviewControl";
import "./style.css";

const examples: Record<string, string> = {
  welcome: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "Welcome! What would you like to order?" }, { type: "Text", value: "Choose from the menu to get started." }] }, null, 2),
  menu: JSON.stringify({ type: "ListView", children: [{ type: "ListViewItem", children: [{ type: "Row", children: [{ type: "Title", value: "Hummus", weight: "semibold" }, { type: "Text", value: "$8.50" }] }] }, { type: "ListViewItem", children: [{ type: "Title", value: "Falafel" }, { type: "Caption", value: "Crisp chickpea bites" }, { type: "Badge", label: "Sold out" }, { type: "Divider" }] }] }, null, 2),
  table: JSON.stringify({ type: "Card", children: [{ type: "Table", children: [{ type: "Table.Row", header: true, children: [{ type: "Table.Cell", children: [{ type: "Text", value: "Dish" }] }, { type: "Table.Cell", align: "end", children: [{ type: "Text", value: "Price" }] }] }, { type: "Table.Row", children: [{ type: "Table.Cell", children: [{ type: "Text", value: "Hummus" }] }, { type: "Table.Cell", align: "end", children: [{ type: "Text", value: "AED 18.00" }] }] }] }] }, null, 2),
  chart: JSON.stringify({ type: "Card", children: [{ type: "Chart", data: [{ day: "Mon", orders: 4, previous: 3 }, { day: "Tue", orders: 7, previous: 5 }, { day: "Wed", orders: 6, previous: 4 }], series: [{ type: "bar", dataKey: "orders", label: "Orders", color: "green" }, { type: "line", dataKey: "previous", label: "Previous", color: "blue" }], xAxis: { dataKey: "day" }, showYAxis: true, showLegend: true }] }, null, 2),
  form: JSON.stringify({ type: "Card", children: [{ type: "Form", children: [{ type: "Title", value: "Order preferences" }, { type: "Input", name: "quantity", inputType: "number", defaultValue: "1", required: true }, { type: "Select", name: "portion", options: [{ value: "regular", label: "Regular" }, { value: "large", label: "Large" }], defaultValue: "regular" }, { type: "Button", label: "Add to order" }] }] }, null, 2),
  arabic: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "مرحباً! ماذا تود أن تطلب؟" }] }, null, 2),
  partial: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "This item is available." }, { type: "Unknown" }, { type: "Text", value: "This item is available too." }] }, null, 2),
  broken: '{ "type": "Card", "children": [',
};

function nodeKey(node: Node, index: number, siblings: Node[]): string {
  if ("key" in node && node.key !== undefined) return `key:${node.key}:${node.kind}`;
  if ((node.kind === "input" || node.kind === "select") && siblings.filter((sibling) => (sibling.kind === "input" || sibling.kind === "select") && sibling.name === node.name).length === 1) return `field:${node.kind}:${node.name}`;
  return `position:${index}:${node.kind}`;
}

type GenericControls = { widget: GenericWidget; disabled: boolean; pending: boolean; retryKey: string | null; retryQuantity: string | null; onAction: (key: string, quantity: string | null) => void };
const GenericControlsContext = createContext<GenericControls | null>(null);

function PreviewNode({ node }: { node: Node }): ReactElement {
  const appearance = node.appearance;
  if (appearance === undefined) return <PreviewNodeContent node={node} />;
  const style: CSSProperties = { width: appearance.width, height: appearance.height, minWidth: appearance.minWidth, paddingInline: appearance.paddingInline, paddingBlock: appearance.paddingBlock, borderWidth: appearance.borderWidth, borderStyle: appearance.borderWidth === undefined ? undefined : "solid", borderColor: appearance.borderColor === "strong" ? "#596653" : appearance.borderColor === "default" ? "#a5afa0" : "#dce2d7", flex: "flex" in node ? node.flex : undefined };
  const classes: string = ["studio-presentation", appearance.theme ? `theme-${appearance.theme}` : "", appearance.size ? `studio-size-${appearance.size}` : "", appearance.variant ? `studio-variant-${appearance.variant}` : "", appearance.primary ? "studio-primary" : "", appearance.uniform ? "studio-uniform" : "", appearance.block ? "studio-block" : "", appearance.flush ? "studio-flush" : ""].filter(Boolean).join(" ");
  return <div className={classes} style={style} lang={appearance.locale} dir={appearance.locale === "ar" ? "rtl" : appearance.locale === "en" ? "ltr" : undefined}><PreviewNodeContent node={node} /></div>;
}

function PreviewNodeContent({ node }: { node: Node }): ReactElement {
  const generic: GenericControls | null = useContext(GenericControlsContext);
  if (node.kind === "button" && node.key !== undefined && generic !== null) {
    const binding = generic.widget.bindings.find((entry) => entry.key === node.key);
    if (binding !== undefined) return <button type="button" disabled={node.disabled === true || generic.pending || !binding.enabled || (generic.disabled && generic.retryKey !== binding.key)} onClick={() => generic.onAction(binding.key, null)}>{binding.label}</button>;
  }
  if (node.kind === "button" || node.kind === "input" || node.kind === "select") return <PreviewControl control={node} disabled={generic?.disabled === true || generic?.pending === true} onChange={node.kind === "select" && node.key !== undefined && generic !== null && generic.widget.bindings.some((binding) => binding.key === node.key && binding.enabled) ? (value) => generic.onAction(node.key!, value) : null} />;
  if ("value" in node) return <p className={[`widget-text widget-${node.kind}`, node.weight ? `weight-${node.weight}` : "", node.color ? `color-${node.color}` : "", node.size ? `${node.kind}-size-${node.size}` : "", node.textAlign ? `text-${node.textAlign}` : "", node.italic ? "italic" : "", node.lineThrough ? "line-through" : ""].filter(Boolean).join(" ")} dir="auto">{node.value}</p>;
  if (node.kind === "badge") return <span className={`widget-badge badge-${node.color ?? "secondary"} badge-${node.variant ?? "soft"}`} dir="auto">{node.label}</span>;
  if (node.kind === "spacer") return <span className="widget-spacer" aria-hidden="true" />;
  if (node.kind === "divider") return <hr className="widget-divider" />;
  if (node.kind === "form") return <PreviewForm scope={node.key ?? null} disabled={generic?.pending === true || (generic?.disabled === true && generic.retryKey !== node.key)} onSubmit={generic !== null && node.key !== undefined && generic.widget.bindings.some((binding) => binding.key === node.key && binding.enabled) ? (value) => generic.onAction(node.key!, value) : null}>{node.children.map((child, index) => <PreviewNode key={child.kind === "input" || child.kind === "select" ? `field:${child.kind}:${child.name}` : nodeKey(child, index, node.children)} node={child} />)}</PreviewForm>;
  if (node.kind === "chart") return <Chart chart={node} />;
  if (node.kind === "table") return <div className="table-scroll"><table className="widget-table"><tbody>{node.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.cells.map((cell, cellIndex) => {
    const content: ReactElement[] = cell.children.map((child, index) => <PreviewNode key={nodeKey(child, index, cell.children)} node={child} />);
    return row.header ? <th key={cellIndex} scope="col" className={cell.align ? `align-${cell.align}` : undefined}>{content}</th> : <td key={cellIndex} className={cell.align ? `align-${cell.align}` : undefined}>{content}</td>;
  })}</tr>)}</tbody></table></div>;
  if (node.kind === "problem") return <p className="problem">{node.message}</p>;
  return <div className={[`widget-${node.kind}`, node.gap === undefined ? "" : `gap-${node.gap}`, node.direction ? `direction-${node.direction}` : "", node.align ? `layout-align-${node.align}` : "", node.justify ? `layout-justify-${node.justify}` : "", node.padding === undefined ? "" : `padding-${node.padding}`, node.flex === undefined ? "" : `flex-${node.flex}`, node.background ? `bg-${node.background}` : "", node.radius ? `radius-${node.radius}` : ""].filter(Boolean).join(" ")}>
    {node.children.length === 0 ? node.kind === "box" ? null : <p className="empty-card">This {node.kind === "list" ? "list" : "container"} is empty.</p>
      : <>{node.children.slice(0, node.appearance?.limit ?? node.children.length).map((child, index) => <PreviewNode key={nodeKey(child, index, node.children)} node={child} />)}{node.appearance?.limit !== undefined && node.children.length > node.appearance.limit && <details><summary>Show more</summary>{node.children.slice(node.appearance.limit).map((child, index) => <PreviewNode key={nodeKey(child, index + node.appearance!.limit!, node.children)} node={child} />)}</details>}</>}
  </div>;
}

// Last line of defence: a render bug in one widget shows a fallback instead of blanking the page.
class PreviewBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError(): { failed: boolean } { return { failed: true }; }
  render(): ReactNode { return this.state.failed ? <p className="problem" role="alert">This widget could not be displayed.</p> : this.props.children; }
}

function Preview({ card, controls }: { card: Card; controls?: GenericControls }): ReactElement {
  return <PreviewBoundary><WidgetDraftProvider><GenericControlsContext.Provider value={controls ?? null}><div data-generic-widget={controls?.widget.widget_id} data-revision={controls?.widget.revision}><PreviewNode node={card} /></div>{controls?.retryKey != null && <button type="button" disabled={controls.pending} onClick={() => controls.onAction(controls.retryKey!, controls.retryQuantity)}>Retry widget action</button>}</GenericControlsContext.Provider></WidgetDraftProvider></PreviewBoundary>;
}

const confirmationSchema = z.object({ actionId: z.string().uuid(), cartRevision: z.string().regex(/^[a-f0-9]{64}$/), widgetId: z.string().min(1).max(128).optional(), widgetRevision: z.number().int().positive().optional() }).strict().refine((value) => (value.widgetId === undefined) === (value.widgetRevision === undefined));
type Confirmation = z.infer<typeof confirmationSchema>;
const confirmationStorageKey: string = "restaurant.pendingConfirmation";

function readConfirmation(): Confirmation | null {
  const source: string | null = sessionStorage.getItem(confirmationStorageKey);
  return source === null ? null : confirmationSchema.parse(JSON.parse(source) as unknown);
}

type DisplayedMenu = { menu: Menu; widgets: { en: Card; ar: Card }; ids: { en: string; ar: string }; envelopes: { en: WidgetEnvelope; ar: WidgetEnvelope } };

type ChatMessage = { id: string; role: "user"; text: string } | { id: string; role: "assistant"; text: string; suggestions: ChatReply["suggestions"]; proposedActions: ChatReply["proposed_actions"]; warnings: ChatReply["warnings"]; menuRevision: number; cartRevision: string; widget: Card | null; widgetControl: GenericWidget | null; extraWidgets: { card: Card; control: GenericWidget | null }[]; locale: "en" | "ar"; streaming?: { index: number; node: Node }[]; incomplete?: boolean };

// The backend keeps one menu widget per session (new revisions, same widget_id), so a repeat menu reply edits the first menu bubble instead of stacking a stale copy.
function editMenuInPlace(messages: ChatMessage[]): ChatMessage[] {
  const last: ChatMessage | undefined = messages[messages.length - 1];
  const first: number = messages.findIndex((message) => message.role === "assistant" && message.widget?.kind === "list");
  if (last?.role !== "assistant" || last.widget?.kind !== "list" || first === messages.length - 1) return messages;
  return messages.map((message, index) => index === first && message.role === "assistant" ? { ...message, widget: last.widget, locale: last.locale, menuRevision: last.menuRevision, cartRevision: last.cartRevision } : index === messages.length - 1 ? { ...last, widget: null } : message);
}

function App(): ReactElement {
  const [source, setSource] = useState<string>(examples.welcome);
  const [card, setCard] = useState<Card | null>(null);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [notice, setNotice] = useState<string>("");
  const [pending, setPending] = useState<boolean>(false);
  const requestId = useRef<number>(0);
  const [displayedMenu, setDisplayedMenu] = useState<DisplayedMenu | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [menuError, setMenuError] = useState<string>("");
  const [menuPending, setMenuPending] = useState<boolean>(false);
  const [cart, setCart] = useState<Cart | null>(null);
  const [cartError, setCartError] = useState<string>("");
  const [quantityEdits, setQuantityEdits] = useState<Readonly<Record<string, QuantityEdit>>>({});
  const [cartPending, setCartPending] = useState<boolean>(false);
  const [order, setOrder] = useState<Order | null>(null);
  const [chatText, setChatText] = useState<string>("");
  const [chatLocale, setChatLocale] = useState<"en" | "ar">("en");
  const [localePending, setLocalePending] = useState<boolean>(false);
  const localeAttempt = useRef<{ widget: WidgetEnvelope; lang: "en" | "ar"; actionId: string } | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatPending, setChatPending] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string>("");
  const [route, setRoute] = useState<string>(location.hash);
  useEffect(() => {
    const sync = (): void => setRoute(location.hash);
    addEventListener("hashchange", sync);
    return () => removeEventListener("hashchange", sync);
  }, []);

  async function submitChat(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const text: string = chatText.trim();
    if (!text || chatPending || menu === null || !live) return;
    setChatPending(true);
    setChatError("");
    const clientMessageId: string = crypto.randomUUID();
    setChatMessages((messages: ChatMessage[]) => [...messages, { id: clientMessageId, role: "user", text }]);
    setChatText("");
    let streamed: boolean = false;
    try {
      const activeView: DisplayedMenu | null = activeMenuIndex >= 0 ? displayedMenu : null;
      const renderedViewId: string | null = activeView === null ? null : activeView.ids[chatLocale];
      const menuRevision: number = activeView === null ? menu.revision : activeView.menu.revision;
      const envelope: WidgetEnvelope | null = activeView === null ? null : activeView.envelopes[chatLocale];
      const reply: ChatReply = await streamChat(text, menuRevision, clientMessageId, chatLocale, renderedViewId, envelope === null || renderedMenu === null ? null : { widget_id: envelope.widget_id, revision: envelope.revision, rendered: renderedMenu }, checkoutView === null || renderedConfirmation === null ? null : { widget_id: checkoutView.widget_id, revision: checkoutView.revision, rendered: renderedConfirmation }, (event) => {
        if (event.type === "card") {
          streamed = true;
          setChatMessages((messages: ChatMessage[]) => [...messages, { id: `${clientMessageId}:stream`, role: "assistant", text: event.text ?? "", suggestions: [], proposedActions: [], warnings: [], menuRevision, cartRevision: "", widget: null, widgetControl: null, extraWidgets: [], locale: chatLocale, streaming: [] }]);
        } else {
          setChatMessages((messages: ChatMessage[]) => messages.map((entry, index) => index === messages.length - 1 && entry.role === "assistant" && entry.streaming ? { ...entry, streaming: [...entry.streaming, event] } : entry));
        }
      });
      const textMessage = reply.messages.find((message) => message.kind === "text");
      if (textMessage === undefined || textMessage.message_id !== reply.message_id || textMessage.payload.text !== reply.text) throw new Error("The assistant message envelope does not match the reply.");
      const widgetMessages = reply.messages.filter((message) => message.kind !== "text");
      if (widgetMessages.length !== reply.widget_previews.length) throw new Error("The widget envelopes do not match their validated previews.");
      const validatedWidgets: Card[] = [];
      for (const [index, widgetMessage] of widgetMessages.entries()) {
        const previous = widgetMessage.payload.type === "ListView" ? envelope : chatMessages.flatMap((entry) => entry.role === "assistant" ? [entry.widgetControl, ...entry.extraWidgets.map((extra) => extra.control)] : []).find((control) => control?.widget_id === widgetMessage.widget_id);
        if (widgetMessage.kind === "widget_update" && (previous == null || widgetMessage.widget_id !== previous.widget_id || widgetMessage.revision <= previous.revision)) throw new WidgetActionConflict("The widget update does not match the displayed revision. Resync and try again.");
        const validated: ValidationResult = await validatePayload(JSON.stringify(widgetMessage.payload));
        if (validated.status !== "valid" || JSON.stringify(validated.preview) !== JSON.stringify(reply.widget_previews[index])) throw new WidgetActionConflict("The widget envelope failed validation. The previous view was retained.");
        const controls = reply.widget_controls[index];
        if (controls !== null && (controls.widget_id !== widgetMessage.widget_id || controls.revision !== widgetMessage.revision)) throw new WidgetActionConflict("The widget action bindings do not match the issued widget.");
        validatedWidgets.push(validated.preview);
      }
      const final: ChatMessage = { id: textMessage.message_id, role: "assistant", text: textMessage.payload.text, suggestions: reply.suggestions, proposedActions: reply.proposed_actions, warnings: reply.warnings, menuRevision: reply.menu_revision, cartRevision: reply.cart_revision, widget: validatedWidgets[0] ?? null, widgetControl: reply.widget_controls[0] ?? null, extraWidgets: validatedWidgets.slice(1).map((card, index) => ({ card, control: reply.widget_controls[index + 1] ?? null })), locale: reply.locale };
      setChatMessages((messages: ChatMessage[]) => {
        const updates = widgetMessages.flatMap((message, index) => message.kind === "widget_update" && message.payload.type === "Card" ? [{ id: message.widget_id, card: validatedWidgets[index], control: reply.widget_controls[index] }] : []);
        const retained = (streamed ? messages.slice(0, -1) : messages).map((entry): ChatMessage => {
          if (entry.role !== "assistant") return entry;
          const update = updates.find((item) => item.id === entry.widgetControl?.widget_id);
          return { ...entry, widget: update?.card ?? entry.widget, widgetControl: update?.control ?? entry.widgetControl, extraWidgets: entry.extraWidgets.map((extra) => { const replacement = updates.find((item) => item.id === extra.control?.widget_id); return replacement ? { card: replacement.card, control: replacement.control } : extra; }) };
        });
        const additions = validatedWidgets.flatMap((card, index) => updates.some((update) => update.id === widgetMessages[index].widget_id) ? [] : [{ card, control: reply.widget_controls[index] }]);
        return editMenuInPlace([...retained, { ...final, widget: additions[0]?.card ?? null, widgetControl: additions[0]?.control ?? null, extraWidgets: additions.slice(1) }]);
      });
    } catch (error: unknown) {
      if (streamed) setChatMessages((messages: ChatMessage[]) => messages.map((entry, index) => index === messages.length - 1 && entry.role === "assistant" ? { ...entry, incomplete: true } : entry));
      if (error instanceof WidgetActionConflict) { genericRecovery.current = true; setLive(false); setLiveNotice("The widget update could not be accepted. The last safe view and drafts are retained. Resync to recover."); }
      setChatText(text);
      setChatError(error instanceof Error ? error.message : "Unable to send the message.");
    } finally {
      setChatPending(false);
    }
  }

  const [confirmation, setConfirmation] = useState<Confirmation | null>(readConfirmation);
  const [checkoutRevision, setCheckoutRevision] = useState<string | null>(null);
  const [checkoutView, setCheckoutView] = useState<CheckoutView | null>(null);
  const [confirmationStatus, setConfirmationStatus] = useState<Snapshot["confirmation"]>(null);
  const [checkoutInvalidated, setCheckoutInvalidated] = useState<boolean>(false);

  useEffect(() => {
    if (checkoutView === null) return;
    if (cart !== null && checkoutView.cart_revision !== cart.revision) setCheckoutInvalidated(true);
    if (confirmationStatus !== null && confirmationStatus.sequence >= checkoutView.sequence && (confirmationStatus.widget_id !== checkoutView.widget_id || !confirmationStatus.active)) setCheckoutInvalidated(true);
  }, [checkoutView, cart, confirmationStatus]);
  const orderingMenuRef = useRef<HTMLDivElement | null>(null);
  const pendingChanges = useRef<number>(0);
  const editAttempt = useRef<{ widgetId: string; actionId: string } | null>(null);
  const widgetAttempts = useRef<Map<string, { actionId: string; envelope: WidgetEnvelope }>>(new Map());
  const [genericAttempts, setGenericAttempts] = useState<Readonly<Record<string, string>>>({});
  const [sessionReady, setSessionReady] = useState<boolean>(false);
  const [live, setLive] = useState<boolean>(false);
  const [liveNotice, setLiveNotice] = useState<string>("Connecting to live updates…");
  const [resyncVersion, setResyncVersion] = useState<number>(0);
  const [resyncPending, setResyncPending] = useState<boolean>(false);
  const observedRevision = useRef<number>(0);
  const appliedRevision = useRef<number>(0);
  const invalidRevision = useRef<number | null>(null);
  const genericRecovery = useRef<boolean>(false);
  const acceptedWidgets = useRef<Snapshot["widgets"] | null>(null);


  async function reviewOrder(): Promise<void> {
    if (cart === null || displayedMenu === null || !live || pendingChanges.current > 0 || confirmation !== null || Object.keys(quantityEdits).length > 0 || cart.items.length === 0) return;
    const envelope: WidgetEnvelope = displayedMenu.envelopes[chatLocale];
    if (!envelope.actions.checkout) return;
    pendingChanges.current += 1;
    setLive(false);
    setCartPending(true);
    try {
      const view: CheckoutView = await startWidgetCheckout(envelope.widget_id, envelope.revision, crypto.randomUUID(), cart.revision);
      setCheckoutView(view);
      setCheckoutInvalidated(false);
      setCheckoutRevision(view.cart.revision);
      setOrder(null);
      setCartError("");
    } catch (error: unknown) {
      setCartError(error instanceof Error ? error.message : "Unable to review the order.");
    } finally {
      pendingChanges.current -= 1;
      setCartPending(false);
    }
  }

  function editOrder(): void {
    if (confirmation !== null || pendingChanges.current > 0) return;
    setCheckoutRevision(null);
    setCheckoutView(null);
    setOrder(null);
    window.requestAnimationFrame(() => {
      orderingMenuRef.current?.scrollIntoView({ block: "nearest" });
      orderingMenuRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    });
  }

  async function abandonReview(): Promise<void> {
    if (checkoutView === null || confirmation !== null || pendingChanges.current > 0) return;
    const attempt = editAttempt.current?.widgetId === checkoutView.widget_id ? editAttempt.current : { widgetId: checkoutView.widget_id, actionId: crypto.randomUUID() };
    editAttempt.current = attempt;
    pendingChanges.current += 1;
    setLive(false);
    setCartPending(true);
    try {
      await editWidgetOrder(checkoutView.widget_id, checkoutView.revision, attempt.actionId, checkoutView.cart.revision);
      editAttempt.current = null;
      setCheckoutRevision(null);
      setCheckoutView(null);
      setCartError("");
      window.requestAnimationFrame(() => { orderingMenuRef.current?.scrollIntoView({ block: "nearest" }); orderingMenuRef.current?.querySelector<HTMLInputElement>("input")?.focus(); });
    } catch (error: unknown) {
      setCartError(error instanceof Error ? error.message : "Unable to edit the order.");
    } finally {
      pendingChanges.current -= 1;
      setCartPending(false);
    }
  }

  async function confirmCart(): Promise<void> {
    if (cart === null || !live || pendingChanges.current > 0) return;
    if (confirmation === null && (checkoutView === null || checkoutInvalidated || checkoutRevision === null || checkoutRevision !== cart.revision || !cart.can_checkout || Object.keys(quantityEdits).length > 0)) return;
    pendingChanges.current += 1;
    setLive(false);
    setCartPending(true);
    const attempt: Confirmation = confirmation ?? { actionId: crypto.randomUUID(), cartRevision: cart.revision, widgetId: checkoutView?.widget_id, widgetRevision: checkoutView?.revision };
    setConfirmation(attempt);
    try {
      sessionStorage.setItem(confirmationStorageKey, JSON.stringify(attempt));
      const confirmed: Order = attempt.widgetId !== undefined && attempt.widgetRevision !== undefined ? await confirmWidgetOrder(attempt.widgetId, attempt.widgetRevision, attempt.actionId, attempt.cartRevision) : await confirmOrder(attempt.actionId, attempt.cartRevision);
      setOrder(confirmed);
      setCheckoutRevision(null);
      setCheckoutView(null);
      setQuantityEdits({});
      sessionStorage.removeItem(confirmationStorageKey);
      setConfirmation(null);
      setCart(await fetchCart());
      setCartError("");
    } catch (error: unknown) {
      if (error instanceof ConfirmationConflict) {
        sessionStorage.removeItem(confirmationStorageKey);
        setConfirmation(null);
        setCheckoutView(null);
        setCheckoutRevision(null);
      }
      setCartError(error instanceof Error ? error.message : "Unable to confirm order. Retry to retrieve the result.");
    } finally {
      pendingChanges.current -= 1;
      setCartPending(false);
    }
  }


  useEffect(() => {
    void startSession().then((initial: Cart) => { setCart(initial); setSessionReady(true); }).catch((error: unknown) => setCartError(error instanceof Error ? error.message : "Unable to start session."));
  }, []);

  useEffect(() => {
    if (!sessionReady) return;
    let active: boolean = true;
    let source: EventSource | null = null;
    let retry: number | null = null;
    let heartbeat: number | null = null;
    function applySnapshot(snapshot: Snapshot): void {
      if (acceptedWidgets.current !== null) {
        for (const locale of ["en", "ar"] as const) {
          const old = acceptedWidgets.current[locale];
          const next = snapshot.widgets[locale];
          if (old.widget_id !== next.widget_id || next.revision < old.revision || (next.revision === old.revision && JSON.stringify(next) !== JSON.stringify(old))) throw new Error("The widget update is older or does not match its issued identity.");
        }
      }
      acceptedWidgets.current = snapshot.widgets;
      appliedRevision.current = snapshot.state_revision;
      setQuantityEdits((edits) => Object.fromEntries(Object.entries(edits).map(([id, edit]) => [id, edit.changedRevision === undefined && edit.cartRevision !== snapshot.cart.revision ? { ...edit, changedRevision: snapshot.cart.revision } : edit])));
      setDisplayedMenu({ menu: snapshot.menu, widgets: snapshot.menu_widgets, ids: snapshot.menu_view_ids, envelopes: snapshot.widgets });
      setMenu(snapshot.menu);
      setCart(snapshot.cart);
      setChatLocale(snapshot.locale);
      setConfirmationStatus(snapshot.confirmation);
    }
    function connect(): void {
      if (!active) return;
      source = new EventSource("/api/events");
      source.addEventListener("snapshot", (event: MessageEvent<string>) => { void (async (): Promise<void> => {
        let revision: number = 0;
        try {
          if (!active) return;
          if (heartbeat !== null) window.clearTimeout(heartbeat);
          heartbeat = window.setTimeout(() => {
            setLive(false);
            setLiveNotice("Live updates timed out. Reconnecting…");
            source?.close();
            retry = window.setTimeout(connect, 2000);
          }, 10000);
          revision = readSnapshotRevision(event.data);
          if (genericRecovery.current) return;
          if (revision < observedRevision.current) return;
          observedRevision.current = revision;
          if (invalidRevision.current !== null && revision <= invalidRevision.current) return;
          if (revision > appliedRevision.current) {
            const snapshot: Snapshot = parseSnapshot(event.data);
            await validateSnapshot(snapshot);
            if (!active || revision < observedRevision.current) return;
            if (pendingChanges.current > 0) return;
            applySnapshot(snapshot);
          }
          if (pendingChanges.current > 0) return;
          invalidRevision.current = null;
          setLive(true);
          setLiveNotice("");
        } catch (error: unknown) {
          if (!active || (revision > 0 && revision < observedRevision.current)) return;
          if (heartbeat !== null) window.clearTimeout(heartbeat);
          setLive(false);
          invalidRevision.current = observedRevision.current;
          setLiveNotice("The live update could not be read. The last safe view is retained. Resync to recover.");
          source?.close();
          retry = window.setTimeout(connect, 2000);
        }
      })(); });
      source.addEventListener("session_expired", () => {
        if (!active) return;
        if (heartbeat !== null) window.clearTimeout(heartbeat);
        setLive(false);
        setLiveNotice("Your session expired. Refresh the page to start again.");
        source?.close();
      });
      source.onerror = () => {
        if (!active) return;
        if (heartbeat !== null) window.clearTimeout(heartbeat);
        setLive(false);
        setLiveNotice("Live updates disconnected. Reconnecting and refreshing your cart…");
      };
    }
    async function resynchronize(): Promise<void> {
      setResyncPending(true);
      try {
        const snapshot: Snapshot = await fetchState();
        await validateSnapshot(snapshot);
        const genericStates: GenericState[] = await fetchGenericState();
        if (!active) return;
        if (snapshot.state_revision < appliedRevision.current) throw new Error("State synchronization returned an older snapshot. Retry Resync.");
        if (pendingChanges.current > 0) throw new Error("Wait for pending changes, then retry Resync.");
        applySnapshot(snapshot);
        setChatMessages((messages) => messages.map((message): ChatMessage => {
          if (message.role !== "assistant") return message;
          const current = genericStates.find((state) => state.widget.widget_id === message.widgetControl?.widget_id);
          return { ...message, widget: current?.preview ?? message.widget, widgetControl: current?.widget ?? message.widgetControl, extraWidgets: message.extraWidgets.map((extra) => { const state = genericStates.find((entry) => entry.widget.widget_id === extra.control?.widget_id); return state === undefined ? extra : { card: state.preview, control: state.widget }; }) };
        }));
        observedRevision.current = snapshot.state_revision;
        invalidRevision.current = null;
        genericRecovery.current = false;
        setLiveNotice("State restored. Waiting for live updates…");
        connect();
      } catch (error: unknown) {
        if (!active) return;
        setLive(false);
        setLiveNotice(error instanceof Error ? error.message : "State synchronization failed. Retry Resync.");
      } finally {
        if (active) setResyncPending(false);
      }
    }
    if (resyncVersion > 0) void resynchronize();
    else connect();
    return () => { active = false; source?.close(); if (retry !== null) window.clearTimeout(retry); if (heartbeat !== null) window.clearTimeout(heartbeat); };
  }, [sessionReady, resyncVersion]);

  function editQuantity(itemId: string, edit: QuantityEdit | null): void {
    setQuantityEdits((current: Readonly<Record<string, QuantityEdit>>) => {
      const { [itemId]: removed, ...remaining } = current;
      return edit === null ? remaining : { ...remaining, [itemId]: edit };
    });
  }

  async function changeQuantity({ itemId, quantity, cartRevision, actionId }: CartChange): Promise<Cart | null> {
    if (cart === null || !live || pendingChanges.current > 0 || confirmation !== null || checkoutRevision !== null || order !== null) return null;
    pendingChanges.current += 1;
    setLive(false);
    setCartPending(true);
    try {
      const next: Cart = await updateCart(itemId, quantity, actionId, cartRevision);
      setCart(next);
      setCartError("");
      return next;
    } catch (error: unknown) {
      setCartError(error instanceof Error ? error.message : "Unable to update cart.");
      return null;
    } finally {
      pendingChanges.current -= 1;
      setCartPending(false);
    }
  }


  async function changeWidgetQuantity(change: CartChange, envelope: WidgetEnvelope): Promise<boolean> {
    if (cart === null || !live || pendingChanges.current > 0 || confirmation !== null || checkoutRevision !== null || order !== null) return false;
    const attempt = widgetAttempts.current.get(change.itemId);
    const original: WidgetEnvelope = attempt?.actionId === change.actionId ? attempt.envelope : envelope;
    const binding = original.actions.quantities.find((entry) => entry.item_id === change.itemId);
    if (binding === undefined || change.quantity < binding.minimum || change.quantity > binding.maximum) { setCartError("This quantity is not permitted by the displayed widget. Refresh and try again."); return false; }
    widgetAttempts.current.set(change.itemId, { actionId: change.actionId, envelope: original });
    pendingChanges.current += 1;
    setLive(false);
    setCartPending(true);
    try {
      const next: Cart = await updateWidgetCart(original.widget_id, original.revision, change.actionId, change.itemId, binding.position, change.quantity, change.cartRevision, change.actionType);
      widgetAttempts.current.delete(change.itemId);
      setCart(next);
      setCartError("");
      return true;
    } catch (error: unknown) {
      setCartError(error instanceof Error ? error.message : "Unable to update cart.");
      return false;
    } finally {
      pendingChanges.current -= 1;
      setCartPending(false);
    }
  }

  async function changeGenericWidget(widget: GenericWidget, key: string, quantity: string | null): Promise<void> {
    const binding = widget.bindings.find((entry) => entry.key === key);
    if (binding?.type === "cart.set_quantity" && (quantity === null || !/^[0-9]+$/.test(quantity) || Number(quantity) > 99 || !binding.quantities?.includes(Number(quantity)))) { setChatError("Choose a whole quantity between 0 and 99."); return; }
    const attemptKey: string = `${widget.widget_id}:${key}:${quantity ?? ""}`;
    const existing: string | undefined = genericAttempts[attemptKey];
    if (binding === undefined || !binding.enabled || !live || pendingChanges.current > 0 || confirmation !== null || checkoutRevision !== null || order !== null || (existing === undefined && (menu?.revision !== widget.menu_revision || cart?.revision !== widget.cart_revision))) return;
    const actionId: string = existing ?? crypto.randomUUID();
    setGenericAttempts((attempts) => ({ ...attempts, [attemptKey]: actionId }));
    pendingChanges.current += 1;
    setLive(false);
    setCartPending(true);
    try {
      const next: Cart = await updateWidgetCart(widget.widget_id, widget.revision, actionId, binding.item_id, binding.position, Number(quantity ?? "0"), widget.cart_revision, binding.type === "cart.set_quantity" ? undefined : binding.type);
      if (existing === undefined) setCart(next);
      setGenericAttempts((attempts) => { const { [attemptKey]: removed, ...remaining } = attempts; return remaining; });
      setChatError("");
    } catch (error: unknown) {
      if (error instanceof WidgetActionConflict) setGenericAttempts((attempts) => { const { [attemptKey]: removed, ...remaining } = attempts; return remaining; });
      const message: string = error instanceof Error ? error.message : "Unable to apply widget action.";
      setChatError(error instanceof WidgetActionConflict ? message : `${message} Retry the same button to retrieve the result.`);
    } finally {
      pendingChanges.current -= 1;
      setCartPending(false);
    }
  }

  function controlsFor(widget: GenericWidget | null): GenericControls | undefined {
    if (widget === null) return undefined;
    const retryKey: string | null = widget.bindings.find((binding) => Object.keys(genericAttempts).some((key) => key.startsWith(`${widget.widget_id}:${binding.key}:`)))?.key ?? null;
    const retryAttempt: string | undefined = retryKey === null ? undefined : Object.keys(genericAttempts).find((key) => key.startsWith(`${widget.widget_id}:${retryKey}:`));
    const retryQuantity: string | null = retryAttempt === undefined || retryKey === null ? null : retryAttempt.slice(`${widget.widget_id}:${retryKey}:`.length) || null;
    return { widget, retryQuantity, pending: cartPending, disabled: !live || confirmation !== null || checkoutRevision !== null || order !== null || menu?.revision !== widget.menu_revision || cart?.revision !== widget.cart_revision || retryKey !== null, retryKey: live && confirmation === null && checkoutRevision === null && order === null ? retryKey : null, onAction: (key: string, quantity: string | null) => { void changeGenericWidget(widget, key, quantity); } };
  }


  async function refreshMenu(): Promise<void> {
    setMenuPending(true);
    try {
      const next: Menu = await fetchMenu();
      setMenu(next);
      setMenuError("");
      if (cart !== null) setCart(await fetchCart());
    } catch (error: unknown) {
      setMenuError(error instanceof Error ? error.message : "Unable to load the menu.");
    } finally {
      setMenuPending(false);
    }
  }

  useEffect(() => { void refreshMenu(); }, []);

  async function sellOut(itemId: string): Promise<void> {
    pendingChanges.current += 1;
    setLive(false);
    setMenuPending(true);
    try {
      const next: Menu = await sellOutItem(itemId);
      setMenu(next);
      setMenuError("");
      if (cart !== null) setCart(await fetchCart());
    } catch (error: unknown) {
      setMenuError(error instanceof Error ? error.message : "Unable to update the menu.");
    } finally {
      pendingChanges.current -= 1;
      setMenuPending(false);
    }
  }

  async function restock(itemId: string): Promise<void> {
    pendingChanges.current += 1;
    setLive(false);
    setMenuPending(true);
    try {
      const next: Menu = await restockItem(itemId);
      setMenu(next);
      setMenuError("");
      if (cart !== null) setCart(await fetchCart());
    } catch (error: unknown) {
      setMenuError(error instanceof Error ? error.message : "Unable to restock the item.");
    } finally {
      pendingChanges.current -= 1;
      setMenuPending(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const id: number = ++requestId.current;
    setNotice("");
    if (new TextEncoder().encode(source).length > 32768) {
      setPending(false);
      setResult(null);
      setNotice("The source exceeds the 32 KiB limit. Reduce it and try again.");
      return;
    }
    setPending(true);
    try {
      const next: ValidationResult = await validatePayload(source);
      if (id !== requestId.current) return;
      setResult(next);
      if (next.preview !== null) setCard(next.preview);
      else setNotice("The payload could not be displayed. The last preview, if present, may be out of date.");
    } catch (error: unknown) {
      if (id !== requestId.current) return;
      setResult(null);
      setNotice(error instanceof Error ? `${error.message} The last preview, if present, may be out of date.` : "Validation failed. Please try again.");
    } finally {
      if (id === requestId.current) setPending(false);
    }
  }

  const activeMenuIndex: number = chatMessages.reduce((last: number, message: ChatMessage, index: number) => message.role === "assistant" && message.widget?.kind === "list" ? index : last, -1);

  const activeEnvelope: WidgetEnvelope | null = activeMenuIndex < 0 || displayedMenu === null ? null : displayedMenu.envelopes[chatLocale];
  const menuDisabled: boolean = cartPending || confirmation !== null || checkoutRevision !== null || order !== null || !live;
  const renderedMenu: RenderedView | null = activeEnvelope === null || cart === null ? null : {
    locale: chatLocale,
    rows: activeEnvelope.menu.items.map((item) => {
      const quantity: number = cart.items.find((entry) => entry.id === item.id)?.quantity ?? 0;
      const edit: QuantityEdit | undefined = quantityEdits[item.id];
      const value: string = edit?.value ?? String(quantity);
      const maximum: number = item.available ? 99 : quantity;
      const issues: ("invalid_quantity" | "stale_cart" | "sold_out")[] = [];
      const valid: boolean = /^[0-9]{1,2}$/.test(value) && Number(value) <= maximum;
      const stale: boolean = edit !== undefined && (edit.cartRevision !== cart.revision || edit.changedRevision !== undefined);
      if (!valid) issues.push("invalid_quantity");
      if (stale) issues.push("stale_cart");
      if (!item.available) issues.push("sold_out");
      return { item_id: item.id, position: item.position, sold_out: !item.available, placeholder: false, quantity: value, draft: edit !== undefined, edit_revision: edit?.cartRevision ?? null, changed_revision: edit?.changedRevision ?? null, disabled: menuDisabled, controls: { input: menuDisabled, decrease: menuDisabled || stale || edit !== undefined || quantity === 0, increase: menuDisabled || stale || edit !== undefined || !item.available || quantity >= 99, apply: menuDisabled || stale || !valid || edit === undefined, remove: menuDisabled || stale || quantity === 0 }, issues };
    }),
    checkout_disabled: menuDisabled || cart.items.length === 0 || Object.keys(quantityEdits).length > 0,
  };
  const renderedMenuJson: string = JSON.stringify(renderedMenu);
  const renderedConfirmation: ConfirmationRenderedView | null = checkoutView === null || cart === null || checkoutRevision === null || confirmation !== null || order !== null ? null : (() => {
    const stale: boolean = checkoutInvalidated || cart.revision !== checkoutRevision;
    const drafts: boolean = Object.keys(quantityEdits).length > 0;
    const disabled: boolean = cartPending || !live;
    const issues: ConfirmationRenderedView["issues"] = [];
    if (stale) issues.push("stale");
    if (drafts) issues.push("drafts");
    if (!cart.can_checkout && cart.items.length > 0) issues.push("sold_out");
    if (disabled) issues.push("disconnected");
    return { locale: chatLocale, rows: checkoutView.cart.items.map((item) => ({ item_id: item.id, quantity: item.quantity, sold_out: !item.available })), edit_disabled: disabled || !checkoutView.actions.some((action) => action.type === "order.edit" && action.enabled), confirm_disabled: disabled || stale || drafts || !cart.can_checkout || !checkoutView.actions.some((action) => action.type === "order.confirm" && action.enabled), issues };
  })();
  const renderedConfirmationJson: string = JSON.stringify(renderedConfirmation);
  async function changeLocale(lang: "en" | "ar"): Promise<void> {
    if (localePending || chatPending || pendingChanges.current > 0 || displayedMenu === null || !live || lang === chatLocale) return;
    const previous = localeAttempt.current;
    const attempt = previous?.lang === lang ? previous : { widget: displayedMenu.envelopes[chatLocale], lang, actionId: crypto.randomUUID() };
    localeAttempt.current = attempt;
    setLocalePending(true);
    pendingChanges.current += 1;
    setLive(false);
    try {
      await setWidgetLocale(attempt.widget, attempt.lang, attempt.actionId);
      localeAttempt.current = null;
      setChatLocale(lang);
      setChatError("");
    } catch (error: unknown) {
      if (error instanceof WidgetActionConflict) localeAttempt.current = null;
      setChatError(error instanceof Error ? error.message : "Unable to change language.");
    } finally {
      pendingChanges.current -= 1;
      setLocalePending(false);
    }
  }
  useEffect(() => {
    if (activeEnvelope === null || renderedMenu === null || cart === null || activeEnvelope.cart_revision !== cart.revision) return;
    let active: boolean = true;
    void acknowledgeWidget(activeEnvelope, renderedMenu).catch((error: unknown) => {
      if (active) setChatError(error instanceof Error ? error.message : "Widget acknowledgement failed.");
    });
    return () => { active = false; };
  }, [activeEnvelope?.widget_id, activeEnvelope?.revision, renderedMenuJson]);

  useEffect(() => {
    if (checkoutView === null || renderedConfirmation === null) return;
    let active: boolean = true;
    void acknowledgeConfirmation(checkoutView, renderedConfirmation).catch((error: unknown) => {
      if (active) {
        setCheckoutInvalidated(true);
        setCartError(error instanceof Error ? error.message : "Confirmation acknowledgement failed. Review your cart again.");
      }
    });
    return () => { active = false; };
  }, [checkoutView?.widget_id, checkoutView?.revision, renderedConfirmationJson]);

  if (route !== "#/lab") return <main className="chat-page" lang={chatLocale} dir={chatLocale === "ar" ? "rtl" : "ltr"}>
    <header className="chat-topbar"><span className="brand-mark" aria-hidden="true">W</span><h1 id="chat-title">{chatLocale === "ar" ? "مساعد المطعم" : "Restaurant assistant"}</h1><div className="chat-language"><label htmlFor="chat-language" className="visually-hidden">Language</label><select id="chat-language" value={chatLocale} disabled={localePending || cartPending || chatPending || displayedMenu === null || !live} onChange={(event) => { void changeLocale(event.target.value as "en" | "ar"); }}><option value="en">English</option><option value="ar">العربية</option></select></div><a href="#/lab" className="lab-link">{chatLocale === "ar" ? "مختبر الودجت" : "Widget lab"}</a></header>
    <section className="chat-body" aria-labelledby="chat-title">
      {chatMessages.length === 0 && <div className="chat-greeting"><p>{chatLocale === "ar" ? "مرحباً، أنا هنا لمساعدتك في اختيار طلبك." : "Hello, I'm here to help you choose and place your order."}</p><div className="chat-starters">{(chatLocale === "ar" ? ["اعرض القائمة", "أضف حمص واحد"] : ["Show me the menu", "Add one hummus"]).map((starter: string) => <button type="button" key={starter} onClick={() => setChatText(starter)}>{starter}</button>)}</div><small>{chatLocale === "ar" ? "تتطلب تغييرات السلة المقترحة موافقتك." : "Suggested cart changes need your approval."}</small></div>}
      <div className="chat-history" aria-live="polite">{chatMessages.map((message, index) => <div key={message.id} className={`chat-message chat-${message.role}`}><strong>{message.role === "user" ? "You" : "Assistant"}</strong><p dir="auto">{message.text}</p>{message.role === "assistant" && message.warnings.length > 0 && <p className="notice" role="status">{message.locale === "ar" ? "تم تصحيح السعر باستخدام قائمة المطعم." : "A price was corrected using the restaurant menu."}</p>}{message.role === "assistant" && (message.streaming || message.widget?.kind === "card") && <div className="summary-card" role="region" aria-label={message.locale === "ar" ? "ملخص المساعد" : "Assistant summary"} aria-busy={message.widget === null && !message.incomplete} tabIndex={0} lang={message.locale} dir={message.locale === "ar" ? "rtl" : "ltr"}>{message.widget ? <Preview card={message.widget} controls={controlsFor(message.widgetControl)} /> : <div className="widget-card">{message.streaming?.map((component) => <PreviewNode key={component.index} node={component.node} />)}</div>}{message.incomplete && <p className="problem" role="status">{message.locale === "ar" ? "هذا الملخص غير مكتمل." : "This summary is incomplete."}</p>}</div>}{message.role === "assistant" && message.widget?.kind === "list" && <div className="chat-widget" ref={index === activeMenuIndex ? orderingMenuRef : null} lang={index === activeMenuIndex ? chatLocale : message.locale} dir={(index === activeMenuIndex ? chatLocale : message.locale) === "ar" ? "rtl" : "ltr"}>{index === activeMenuIndex && displayedMenu && cart ? <OrderingMenu menu={displayedMenu.menu} cart={cart} card={displayedMenu.widgets[chatLocale]} locale={chatLocale} disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null || !live} error={cartError} edits={quantityEdits} onEdit={editQuantity} onReview={() => { void reviewOrder(); }} onChange={(change: CartChange) => changeWidgetQuantity(change, displayedMenu.envelopes[chatLocale])} renderNode={(node: Node) => <PreviewNode node={node} />} /> : <Preview card={message.widget} />}</div>}{message.role === "assistant" && message.extraWidgets.map(({ card, control }, widgetIndex) => <div key={widgetIndex} className="summary-card" role="region" aria-label={message.locale === "ar" ? "ملخص المساعد" : "Assistant summary"} lang={message.locale} dir={message.locale === "ar" ? "rtl" : "ltr"}><Preview card={card} controls={controlsFor(control)} /></div>)}{message.role === "assistant" && message.suggestions.map((suggestion) => <button type="button" key={suggestion.item_id} disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null || !live || menu?.revision !== message.menuRevision || cart?.revision !== message.cartRevision} onClick={() => { void changeQuantity({ itemId: suggestion.item_id, quantity: suggestion.quantity, cartRevision: message.cartRevision, actionId: crypto.randomUUID() }).then((next: Cart | null) => { if (next !== null) setChatMessages((messages: ChatMessage[]) => messages.map((entry) => entry.id === message.id && entry.role === "assistant" ? { ...entry, suggestions: entry.suggestions.filter((item) => item.item_id !== suggestion.item_id), cartRevision: next.revision } : entry)); }); }}>Set {suggestion.item_id} quantity to {suggestion.quantity}</button>)}{message.role === "assistant" && message.proposedActions.map((action, actionIndex) => action.type === "locale.set" && action.lang !== null ? <button type="button" key={actionIndex} disabled={localePending || !live || action.lang === chatLocale} onClick={() => { if (action.lang !== null) void changeLocale(action.lang); }}>Switch language to {action.lang === "ar" ? "العربية" : "English"}</button> : <button type="button" key={actionIndex} disabled={cartPending || !live || checkoutRevision !== null || order !== null || cart === null || cart.items.length === 0 || Object.keys(quantityEdits).length > 0 || activeMenuIndex < 0} onClick={() => { void reviewOrder(); }}>Review order</button>)}</div>)}
        {order ? <OrderReceipt order={order} locale={chatLocale} disabled={cartPending || !live} onStart={editOrder} /> : confirmation ? <ConfirmationRecovery locale={chatLocale} disabled={cartPending || !live} error={cartError} onRetry={() => { void confirmCart(); }} /> : checkoutRevision !== null && checkoutView !== null && cart && <OrderReview invalidated={checkoutInvalidated} view={checkoutView} renderCard={(card: Card) => <Preview card={card} />} cart={cart} reviewedRevision={checkoutRevision} locale={chatLocale} disabled={cartPending || !live} hasDrafts={Object.keys(quantityEdits).length > 0} error={cartError} onEdit={() => { void abandonReview(); }} onReview={() => { void reviewOrder(); }} onConfirm={() => { void confirmCart(); }} />}
      </div>
    </section>
    <div className="chat-composer">
      {liveNotice && <div className="notice" role="status">{liveNotice} <button type="button" disabled={!sessionReady || cartPending || resyncPending} onClick={() => { setLive(false); setLiveNotice("Synchronizing widgets…"); setResyncVersion((version: number) => version + 1); }}>{resyncPending ? "Synchronizing…" : "Resync"}</button></div>}
      {chatError && <p className="notice" role="alert">{chatError}</p>}
      <form className="chat-form" onSubmit={(event) => { void submitChat(event); }}><label htmlFor="chat-input" className="visually-hidden">Your message</label><textarea id="chat-input" value={chatText} onChange={(event) => setChatText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} maxLength={2000} rows={1} placeholder={chatLocale === "ar" ? "اكتب رسالتك…" : "Type anything…"} /><button type="submit" className="send-button" aria-label={chatPending ? "Thinking…" : "Send message"} aria-busy={chatPending} disabled={chatPending || !live || !chatText.trim()}><svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M7 17 17 7M8 7h9v9" /></svg></button></form>
    </div>
  </main>;
  return <main className="shell">
    <header className="masthead"><div className="brand"><span className="brand-mark">W</span><span>Widget lab</span></div><nav className="masthead-nav"><a href="#/" className="assistant-link"><span aria-hidden="true">← </span>Back to assistant</a><span className="badge">PLAYGROUND <span> / 01</span></span></nav></header>
    <section className="intro"><p className="eyebrow">VALIDATE &amp; PREVIEW</p><h1>See your widget<br /><em>come to life.</em></h1><p>Paste a widget payload to inspect how it renders. Supports menu layouts, text, badges, dividers, tables, charts and form previews.</p></section>
    <div className="workspace">
      <form className="panel editor" onSubmit={(event) => { void submit(event); }}>
        <div className="panel-heading"><div><span className="step">01 / INPUT</span><h2>Widget payload</h2></div><span className="format">JSON</span></div>
        <div className="example-row"><label htmlFor="example">Load an example</label><select id="example" defaultValue="welcome" onChange={(event) => setSource(examples[event.target.value])}><option value="welcome">Welcome card</option><option value="menu">Nested menu</option><option value="table">Table</option><option value="chart">Chart</option><option value="form">Form controls</option><option value="arabic">Arabic text</option><option value="partial">Unsupported child</option><option value="broken">Malformed JSON</option></select></div>
        <label className="source-label" htmlFor="source">Payload source</label>
        <textarea id="source" spellCheck={false} value={source} onChange={(event) => setSource(event.target.value)} aria-describedby="source-help" />
        <div className="editor-footer"><span id="source-help">Maximum source size: 32 KiB</span><button type="submit">{pending ? "Validating…" : "Validate widget"}<span aria-hidden="true"> ↗</span></button></div>
      </form>
      <section className="panel output" aria-labelledby="preview-title"><div className="panel-heading"><div><span className="step">02 / OUTPUT</span><h2 id="preview-title">Preview</h2></div><span className="live-dot">RENDER</span></div>
        <div className="preview-area" aria-busy={pending}>{card ? <Preview key={`${card.kind}:${card.key ?? ""}`} card={card} /> : <div className="empty-state"><span className="empty-icon" aria-hidden="true">◇</span><p>Your preview will appear here.</p><small>Validate a payload to get started.</small></div>}</div>
        <div className="diagnostics" aria-live="polite"><div className="diagnostics-heading"><h3>Validation</h3><span>{result ? result.status.toUpperCase() : "AWAITING INPUT"}</span></div>
          {notice && <p className="notice" role="alert">{notice}</p>}
          {result && result.issues.length > 0 ? <ul>{result.issues.map((item, index) => <li key={index}><strong>{item.severity}</strong><code>{item.path}</code><span>{item.message}</span></li>)}</ul> : <p className="quiet">{result ? "No issues found." : "Issues and validation details will show here."}</p>}
        </div>
      </section>
    </div>
    <section className="panel menu-panel" aria-labelledby="menu-title">
      <div className="menu-heading"><div><span className="step">RESTAURANT / المطعم</span><h2 id="menu-title">Demo menu <span lang="ar" dir="rtl"> / قائمة الطعام</span></h2></div><button type="button" onClick={() => { void refreshMenu(); }} disabled={menuPending}>Refresh menu</button></div>
      <p className="menu-help">Mock restaurant data · Mark an item sold out or restock it to try an inventory update. Changes appear automatically in other tabs.</p>
      {liveNotice && <p className="notice" role="status">{liveNotice}</p>}
      <button type="button" disabled={!sessionReady || cartPending || resyncPending} onClick={() => { setLive(false); setLiveNotice("Synchronizing widgets…"); setResyncVersion((version: number) => version + 1); }}>{resyncPending ? "Synchronizing…" : "Resync"}</button>
      {menuError && <p className="notice" role="alert">{menuError}</p>}
      {menu && <><p className="menu-revision">Menu version {menu.revision}</p><ul className="menu-list">{menu.items.map((item) => <li key={item.id}>
        <div><strong>{item.name.en}</strong><span className="menu-ar" lang="ar" dir="rtl">{item.name.ar}</span><span className="menu-price">AED {(item.price_minor / 100).toFixed(2)} · {item.available ? "Available / متوفر" : "Sold out / نفد"}</span></div>
        <div className="menu-actions"><button type="button" disabled={cartPending || !live || confirmation !== null || checkoutRevision !== null || order !== null || cart === null || !item.available || (cart.items.find((entry) => entry.id === item.id)?.quantity ?? 0) >= 99} onClick={() => { if (cart) void changeQuantity({ itemId: item.id, quantity: (cart.items.find((entry) => entry.id === item.id)?.quantity ?? 0) + 1, cartRevision: cart.revision, actionId: crypto.randomUUID() }); }}>Add to cart</button><button type="button" disabled={menuPending} onClick={() => { if (item.available) { void sellOut(item.id); } else { void restock(item.id); } }}>{item.available ? "Mark sold out" : "Restock"}</button></div>
      </li>)}</ul></>}
    </section>
    <section className="panel menu-panel" aria-labelledby="cart-title">
      <div className="menu-heading"><div><span className="step">YOUR ORDER / طلبك</span><h2 id="cart-title">Your cart</h2></div><button type="button" disabled={cartPending || cart === null} onClick={() => { void fetchCart().then(setCart).catch((error: unknown) => setCartError(error instanceof Error ? error.message : "Unable to refresh cart.")); }}>Refresh cart</button></div>
      {cartError && <p className="notice" role="alert">{cartError}</p>}
      {cart && (cart.items.length === 0 ? <p className="menu-help">Your cart is empty.</p> : <><ul className="menu-list">{cart.items.map((item) => <li key={item.id}><div><strong>{item.name_en} <span lang="ar" dir="rtl">{item.name_ar}</span></strong><span className="menu-price">{item.quantity} × AED {(item.price_minor / 100).toFixed(2)} {!item.available && "· Sold out / نفد"}</span></div><div className="menu-actions"><button type="button" disabled={cartPending || !live || confirmation !== null || checkoutRevision !== null || order !== null} onClick={() => { void changeQuantity({ itemId: item.id, quantity: item.quantity - 1, cartRevision: cart.revision, actionId: crypto.randomUUID() }); }} aria-label={`Remove one ${item.name_en}`}>−</button><button type="button" disabled={cartPending || !live || confirmation !== null || checkoutRevision !== null || order !== null || !item.available || item.quantity >= 99} onClick={() => { void changeQuantity({ itemId: item.id, quantity: item.quantity + 1, cartRevision: cart.revision, actionId: crypto.randomUUID() }); }} aria-label={`Add one ${item.name_en}`}>+</button></div></li>)}</ul><p className="menu-help">Selected items total: AED {(cart.total_minor / 100).toFixed(2)}</p>{!cart.can_checkout && <p className="notice">A selected item is sold out. Remove it or restock it before confirming.</p>}<button type="button" disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null || !live || Object.keys(quantityEdits).length > 0} onClick={() => { void reviewOrder(); }}>Review order</button></>)}
    </section>
    <footer><span>WIDGET LAB <span className="footer-slash">/</span> PAYLOAD PLAYGROUND</span><span>Built for careful experimentation.</span></footer>
  </main>;
}

const root: HTMLElement | null = document.getElementById("root");
if (root === null) throw new Error("Application root is missing.");
const reactRoot = createRoot(root);
reactRoot.render(<StrictMode><App /></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => { reactRoot.unmount(); });
