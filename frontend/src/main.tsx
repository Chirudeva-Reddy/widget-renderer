import { StrictMode, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactElement } from "react";
import { createRoot } from "react-dom/client";
import { z } from "zod";
import { ConfirmationConflict, confirmOrder, fetchCart, fetchMenu, parseSnapshot, restockItem, sellOutItem, sendChat, startSession, updateCart, validatePayload } from "./api";
import type { Card, Cart, ChatReply, Menu, Node, Order, Snapshot, ValidationResult } from "./api";
import { Chart } from "./Chart";
import { ConfirmationRecovery, OrderReceipt, OrderReview } from "./CheckoutWidget";
import { OrderingMenu } from "./OrderingMenu";
import type { CartChange, QuantityEdit } from "./OrderingMenu";
import { PreviewControl } from "./PreviewControl";
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

function PreviewNode({ node }: { node: Node }): ReactElement {
  if (node.kind === "button" || node.kind === "input" || node.kind === "select") return <PreviewControl control={node} />;
  if ("value" in node) return <p className={`widget-text widget-${node.kind}${node.weight ? ` weight-${node.weight}` : ""}`} dir="auto">{node.value}</p>;
  if (node.kind === "badge") return <span className="widget-badge" dir="auto">{node.label}</span>;
  if (node.kind === "divider") return <hr className="widget-divider" />;
  if (node.kind === "form") return <fieldset className="widget-form"><legend>Form preview · actions disabled</legend>{node.children.map((child, index) => <PreviewNode key={index} node={child} />)}</fieldset>;
  if (node.kind === "chart") return <Chart chart={node} />;
  if (node.kind === "table") return <div className="table-scroll"><table className="widget-table"><tbody>{node.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.cells.map((cell, cellIndex) => {
    const content: ReactElement[] = cell.children.map((child, index) => <PreviewNode key={index} node={child} />);
    return row.header ? <th key={cellIndex} scope="col" className={cell.align ? `align-${cell.align}` : undefined}>{content}</th> : <td key={cellIndex} className={cell.align ? `align-${cell.align}` : undefined}>{content}</td>;
  })}</tr>)}</tbody></table></div>;
  if (node.kind === "problem") return <p className="problem">{node.message}</p>;
  return <div className={`widget-${node.kind}${node.gap !== undefined ? ` gap-${node.gap}` : ""}`}>
    {node.children.length === 0 ? <p className="empty-card">This {node.kind === "list" ? "list" : "container"} is empty.</p>
      : node.children.map((child, index) => <PreviewNode key={index} node={child} />)}
  </div>;
}

function Preview({ card }: { card: Card }): ReactElement {
  return <PreviewNode node={card} />;
}

const confirmationSchema = z.object({ actionId: z.string().uuid(), cartRevision: z.string().regex(/^[a-f0-9]{64}$/) }).strict();
type Confirmation = z.infer<typeof confirmationSchema>;
const confirmationStorageKey: string = "restaurant.pendingConfirmation";

function readConfirmation(): Confirmation | null {
  const source: string | null = sessionStorage.getItem(confirmationStorageKey);
  return source === null ? null : confirmationSchema.parse(JSON.parse(source) as unknown);
}

type DisplayedMenu = { menu: Menu; widgets: { en: Card; ar: Card }; ids: { en: string; ar: string } };

type ChatMessage = { role: "user"; text: string } | { role: "assistant"; text: string; suggestion: ChatReply["suggestion"]; menuRevision: number; cartRevision: string; widget: Card | null; locale: "en" | "ar" };

function App(): ReactElement {
  const [source, setSource] = useState<string>(examples.welcome);
  const [card, setCard] = useState<Card | null>(null);
  const [previewVersion, setPreviewVersion] = useState<number>(0);
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
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatPending, setChatPending] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string>("");

  async function submitChat(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const text: string = chatText.trim();
    if (!text || menu === null || !live) return;
    setChatPending(true);
    setChatError("");
    setChatMessages((messages: ChatMessage[]) => [...messages, { role: "user", text }]);
    setChatText("");
    try {
      const activeView: DisplayedMenu | null = activeMenuIndex >= 0 ? displayedMenu : null;
      const renderedViewId: string | null = activeView === null ? null : activeView.ids[chatLocale];
      const menuRevision: number = activeView === null ? menu.revision : activeView.menu.revision;
      const reply: ChatReply = await sendChat(text, menuRevision, crypto.randomUUID(), chatLocale, renderedViewId);
      setChatMessages((messages: ChatMessage[]) => [...messages, { role: "assistant", text: reply.text, suggestion: reply.suggestion, menuRevision: reply.menu_revision, cartRevision: reply.cart_revision, widget: reply.widget, locale: reply.locale }]);
    } catch (error: unknown) {
      setChatText(text);
      setChatError(error instanceof Error ? error.message : "Unable to send the message.");
    } finally {
      setChatPending(false);
    }
  }

  const [confirmation, setConfirmation] = useState<Confirmation | null>(readConfirmation);
  const [checkoutRevision, setCheckoutRevision] = useState<string | null>(null);
  const orderingMenuRef = useRef<HTMLDivElement | null>(null);
  const pendingChanges = useRef<number>(0);
  const [sessionReady, setSessionReady] = useState<boolean>(false);
  const [live, setLive] = useState<boolean>(false);
  const [liveNotice, setLiveNotice] = useState<string>("Connecting to live updates…");


  function reviewOrder(): void {
    if (cart === null || !live || pendingChanges.current > 0 || confirmation !== null || Object.keys(quantityEdits).length > 0 || cart.items.length === 0) return;
    setCheckoutRevision(cart.revision);
    setOrder(null);
    setCartError("");
  }

  function editOrder(): void {
    if (confirmation !== null || pendingChanges.current > 0) return;
    setCheckoutRevision(null);
    setOrder(null);
    window.requestAnimationFrame(() => {
      orderingMenuRef.current?.scrollIntoView({ block: "nearest" });
      orderingMenuRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    });
  }

  async function confirmCart(): Promise<void> {
    if (cart === null || !live || pendingChanges.current > 0) return;
    if (confirmation === null && (checkoutRevision === null || checkoutRevision !== cart.revision || !cart.can_checkout || Object.keys(quantityEdits).length > 0)) return;
    pendingChanges.current += 1;
    setLive(false);
    setCartPending(true);
    const attempt: Confirmation = confirmation ?? { actionId: crypto.randomUUID(), cartRevision: cart.revision };
    setConfirmation(attempt);
    try {
      sessionStorage.setItem(confirmationStorageKey, JSON.stringify(attempt));
      const confirmed: Order = await confirmOrder(attempt.actionId, attempt.cartRevision);
      setOrder(confirmed);
      setCheckoutRevision(null);
      setQuantityEdits({});
      sessionStorage.removeItem(confirmationStorageKey);
      setConfirmation(null);
      setCart(await fetchCart());
      setCartError("");
    } catch (error: unknown) {
      if (error instanceof ConfirmationConflict) {
        sessionStorage.removeItem(confirmationStorageKey);
        setConfirmation(null);
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
    function connect(): void {
      if (!active) return;
      source = new EventSource("/api/events");
      source.addEventListener("snapshot", (event: MessageEvent<string>) => {
        try {
          const snapshot: Snapshot = parseSnapshot(event.data);
          if (!active) return;
          if (heartbeat !== null) window.clearTimeout(heartbeat);
          heartbeat = window.setTimeout(() => {
            setLive(false);
            setLiveNotice("Live updates timed out. Reconnecting…");
            source?.close();
            retry = window.setTimeout(connect, 2000);
          }, 10000);
          if (pendingChanges.current > 0) return;
          setDisplayedMenu({ menu: snapshot.menu, widgets: snapshot.menu_widgets, ids: snapshot.menu_view_ids });
          setMenu(snapshot.menu);
          setCart(snapshot.cart);
          setLive(true);
          setLiveNotice("");
        } catch (error: unknown) {
          setLive(false);
          setLiveNotice("The live update could not be read. Reconnecting…");
          source?.close();
          retry = window.setTimeout(connect, 2000);
        }
      });
      source.addEventListener("session_expired", () => {
        if (heartbeat !== null) window.clearTimeout(heartbeat);
        setLive(false);
        setLiveNotice("Your session expired. Refresh the page to start again.");
        source?.close();
      });
      source.onerror = () => {
        if (heartbeat !== null) window.clearTimeout(heartbeat);
        setLive(false);
        setLiveNotice("Live updates disconnected. Reconnecting and refreshing your cart…");
      };
    }
    connect();
    return () => { active = false; source?.close(); if (retry !== null) window.clearTimeout(retry); if (heartbeat !== null) window.clearTimeout(heartbeat); };
  }, [sessionReady]);

  function editQuantity(itemId: string, edit: QuantityEdit | null): void {
    setQuantityEdits((current: Readonly<Record<string, QuantityEdit>>) => {
      const { [itemId]: removed, ...remaining } = current;
      return edit === null ? remaining : { ...remaining, [itemId]: edit };
    });
  }

  async function changeQuantity({ itemId, quantity, cartRevision, actionId }: CartChange): Promise<boolean> {
    if (cart === null || !live || pendingChanges.current > 0 || confirmation !== null || checkoutRevision !== null || order !== null) return false;
    pendingChanges.current += 1;
    setLive(false);
    setCartPending(true);
    try {
      const next: Cart = await updateCart(itemId, quantity, actionId, cartRevision);
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
      if (next.preview !== null) { setCard(next.preview); setPreviewVersion((version: number) => version + 1); }
      else setNotice("The payload could not be displayed. The last preview, if present, may be out of date.");
    } catch (error: unknown) {
      if (id !== requestId.current) return;
      setResult(null);
      setNotice(error instanceof Error ? `${error.message} The last preview, if present, may be out of date.` : "Validation failed. Please try again.");
    } finally {
      if (id === requestId.current) setPending(false);
    }
  }

  const activeMenuIndex: number = chatMessages.reduce((last: number, message: ChatMessage, index: number) => message.role === "assistant" && message.widget !== null ? index : last, -1);

  return <main className="shell">
    <header className="masthead"><div className="brand"><span className="brand-mark">W</span><span>Widget lab</span></div><span className="badge">PLAYGROUND <span> / 01</span></span></header>
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
        <div className="preview-area" aria-busy={pending}>{card ? <Preview key={previewVersion} card={card} /> : <div className="empty-state"><span className="empty-icon" aria-hidden="true">◇</span><p>Your preview will appear here.</p><small>Validate a payload to get started.</small></div>}</div>
        <div className="diagnostics" aria-live="polite"><div className="diagnostics-heading"><h3>Validation</h3><span>{result ? result.status.toUpperCase() : "AWAITING INPUT"}</span></div>
          {notice && <p className="notice" role="alert">{notice}</p>}
          {result && result.issues.length > 0 ? <ul>{result.issues.map((item, index) => <li key={index}><strong>{item.severity}</strong><code>{item.path}</code><span>{item.message}</span></li>)}</ul> : <p className="quiet">{result ? "No issues found." : "Issues and validation details will show here."}</p>}
        </div>
      </section>
    </div>
    <section className="panel menu-panel" aria-labelledby="chat-title">
      <div className="menu-heading"><div><span className="step">RESTAURANT ASSISTANT / المساعد</span><h2 id="chat-title">Ask about the menu</h2></div><div><label htmlFor="chat-language">Language </label><select id="chat-language" value={chatLocale} onChange={(event) => setChatLocale(event.target.value as "en" | "ar")}><option value="en">English</option><option value="ar">العربية</option></select></div></div>
      <p className="menu-help">Ask in English or Arabic. Suggested cart changes require your approval.</p>
      <div className="chat-history" aria-live="polite">{chatMessages.length === 0 && <p className="menu-help">Try “Show me the menu” or “Add one hummus”.</p>}{chatMessages.map((message, index) => <div key={index} className={`chat-message chat-${message.role}`}><strong>{message.role === "user" ? "You" : "Assistant"}</strong><p dir="auto">{message.text}</p>{message.role === "assistant" && message.widget && <div className="chat-widget" ref={index === activeMenuIndex ? orderingMenuRef : null} lang={index === activeMenuIndex ? chatLocale : message.locale} dir={(index === activeMenuIndex ? chatLocale : message.locale) === "ar" ? "rtl" : "ltr"}>{index === activeMenuIndex && displayedMenu && cart ? <OrderingMenu menu={displayedMenu.menu} cart={cart} card={displayedMenu.widgets[chatLocale]} locale={chatLocale} disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null || !live} error={cartError} edits={quantityEdits} onEdit={editQuantity} onReview={reviewOrder} onChange={changeQuantity} renderNode={(node: Node) => <PreviewNode node={node} />} /> : <Preview card={message.widget} />}</div>}{message.role === "assistant" && message.suggestion && <button type="button" disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null || !live || menu?.revision !== message.menuRevision || cart?.revision !== message.cartRevision} onClick={() => { if (message.suggestion) { void changeQuantity({ itemId: message.suggestion.item_id, quantity: message.suggestion.quantity, cartRevision: message.cartRevision, actionId: crypto.randomUUID() }).then((success: boolean) => { if (success) setChatMessages((messages: ChatMessage[]) => messages.map((entry, messageIndex) => messageIndex === index && entry.role === "assistant" ? { ...entry, suggestion: null } : entry)); }); } }}>Set {message.suggestion.item_id} quantity to {message.suggestion.quantity}</button>}</div>)}
        {order ? <OrderReceipt order={order} locale={chatLocale} disabled={cartPending || !live} onStart={editOrder} /> : confirmation ? <ConfirmationRecovery locale={chatLocale} disabled={cartPending || !live} error={cartError} onRetry={() => { void confirmCart(); }} /> : checkoutRevision !== null && cart && <OrderReview cart={cart} reviewedRevision={checkoutRevision} locale={chatLocale} disabled={cartPending || !live} hasDrafts={Object.keys(quantityEdits).length > 0} error={cartError} onEdit={editOrder} onReview={reviewOrder} onConfirm={() => { void confirmCart(); }} />}
      </div>
      {chatError && <p className="notice" role="alert">{chatError}</p>}
      <form className="chat-form" onSubmit={(event) => { void submitChat(event); }}><label htmlFor="chat-input">Your message</label><textarea id="chat-input" value={chatText} onChange={(event) => setChatText(event.target.value)} maxLength={2000} rows={2} /><button type="submit" disabled={chatPending || !live || !chatText.trim()}>{chatPending ? "Thinking…" : "Send message"}</button></form>
    </section>
    <section className="panel menu-panel" aria-labelledby="menu-title">
      <div className="menu-heading"><div><span className="step">RESTAURANT / المطعم</span><h2 id="menu-title">Demo menu <span lang="ar" dir="rtl"> / قائمة الطعام</span></h2></div><button type="button" onClick={() => { void refreshMenu(); }} disabled={menuPending}>Refresh menu</button></div>
      <p className="menu-help">Mock restaurant data · Mark an item sold out or restock it to try an inventory update. Changes appear automatically in other tabs.</p>
      {liveNotice && <p className="notice" role="status">{liveNotice}</p>}
      {menuError && <p className="notice" role="alert">{menuError}</p>}
      {menu && <><p className="menu-revision">Menu version {menu.revision}</p><ul className="menu-list">{menu.items.map((item) => <li key={item.id}>
        <div><strong>{item.name.en}</strong><span className="menu-ar" lang="ar" dir="rtl">{item.name.ar}</span><span className="menu-price">AED {(item.price_minor / 100).toFixed(2)} · {item.available ? "Available / متوفر" : "Sold out / نفد"}</span></div>
        <div className="menu-actions"><button type="button" disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null || cart === null || !item.available || (cart.items.find((entry) => entry.id === item.id)?.quantity ?? 0) >= 99} onClick={() => { if (cart) void changeQuantity({ itemId: item.id, quantity: (cart.items.find((entry) => entry.id === item.id)?.quantity ?? 0) + 1, cartRevision: cart.revision, actionId: crypto.randomUUID() }); }}>Add to cart</button><button type="button" disabled={menuPending} onClick={() => { if (item.available) { void sellOut(item.id); } else { void restock(item.id); } }}>{item.available ? "Mark sold out" : "Restock"}</button></div>
      </li>)}</ul></>}
    </section>
    <section className="panel menu-panel" aria-labelledby="cart-title">
      <div className="menu-heading"><div><span className="step">YOUR ORDER / طلبك</span><h2 id="cart-title">Your cart</h2></div><button type="button" disabled={cartPending || cart === null} onClick={() => { void fetchCart().then(setCart).catch((error: unknown) => setCartError(error instanceof Error ? error.message : "Unable to refresh cart.")); }}>Refresh cart</button></div>
      {cartError && <p className="notice" role="alert">{cartError}</p>}
      {cart && (cart.items.length === 0 ? <p className="menu-help">Your cart is empty.</p> : <><ul className="menu-list">{cart.items.map((item) => <li key={item.id}><div><strong>{item.name_en} <span lang="ar" dir="rtl">{item.name_ar}</span></strong><span className="menu-price">{item.quantity} × AED {(item.price_minor / 100).toFixed(2)} {!item.available && "· Sold out / نفد"}</span></div><div className="menu-actions"><button type="button" disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null} onClick={() => { void changeQuantity({ itemId: item.id, quantity: item.quantity - 1, cartRevision: cart.revision, actionId: crypto.randomUUID() }); }} aria-label={`Remove one ${item.name_en}`}>−</button><button type="button" disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null || !item.available || item.quantity >= 99} onClick={() => { void changeQuantity({ itemId: item.id, quantity: item.quantity + 1, cartRevision: cart.revision, actionId: crypto.randomUUID() }); }} aria-label={`Add one ${item.name_en}`}>+</button></div></li>)}</ul><p className="menu-help">Selected items total: AED {(cart.total_minor / 100).toFixed(2)}</p>{!cart.can_checkout && <p className="notice">A selected item is sold out. Remove it or restock it before confirming.</p>}<button type="button" disabled={cartPending || confirmation !== null || checkoutRevision !== null || order !== null || !live || Object.keys(quantityEdits).length > 0} onClick={reviewOrder}>Review order</button></>)}
    </section>
    <footer><span>WIDGET LAB <span className="footer-slash">/</span> PAYLOAD PLAYGROUND</span><span>Built for careful experimentation.</span></footer>
  </main>;
}

const root: HTMLElement | null = document.getElementById("root");
if (root === null) throw new Error("Application root is missing.");
const reactRoot = createRoot(root);
reactRoot.render(<StrictMode><App /></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => { reactRoot.unmount(); });
