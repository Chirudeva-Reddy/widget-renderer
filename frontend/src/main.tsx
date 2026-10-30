import { StrictMode, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactElement } from "react";
import { createRoot } from "react-dom/client";
import { confirmOrder, fetchCart, fetchMenu, restockItem, sellOutItem, startSession, updateCart, validatePayload } from "./api";
import type { Card, Cart, Menu, Node, Order, ValidationResult } from "./api";
import "./style.css";

const examples: Record<string, string> = {
  welcome: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "Welcome! What would you like to order?" }, { type: "Text", value: "Choose from the menu to get started." }] }, null, 2),
  menu: JSON.stringify({ type: "ListView", children: [{ type: "ListViewItem", children: [{ type: "Row", children: [{ type: "Title", value: "Hummus", weight: "semibold" }, { type: "Text", value: "$8.50" }] }] }, { type: "ListViewItem", children: [{ type: "Title", value: "Falafel" }, { type: "Caption", value: "Crisp chickpea bites" }, { type: "Badge", label: "Sold out" }, { type: "Divider" }] }] }, null, 2),
  arabic: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "مرحباً! ماذا تود أن تطلب؟" }] }, null, 2),
  partial: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "This item is available." }, { type: "Unknown" }, { type: "Text", value: "This item is available too." }] }, null, 2),
  broken: '{ "type": "Card", "children": [',
};

function PreviewNode({ node }: { node: Node }): ReactElement {
  if ("value" in node) return <p className={`widget-text widget-${node.kind}${node.weight ? ` weight-${node.weight}` : ""}`} dir="auto">{node.value}</p>;
  if (node.kind === "badge") return <span className="widget-badge" dir="auto">{node.label}</span>;
  if (node.kind === "divider") return <hr className="widget-divider" />;
  if (node.kind === "problem") return <p className="problem">{node.message}</p>;
  return <div className={`widget-${node.kind}${node.gap !== undefined ? ` gap-${node.gap}` : ""}`}>
    {node.children.length === 0 ? <p className="empty-card">This {node.kind === "list" ? "list" : "container"} is empty.</p>
      : node.children.map((child, index) => <PreviewNode key={index} node={child} />)}
  </div>;
}

function Preview({ card }: { card: Card }): ReactElement {
  return <PreviewNode node={card} />;
}

function App(): ReactElement {
  const [source, setSource] = useState<string>(examples.welcome);
  const [card, setCard] = useState<Card | null>(null);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [notice, setNotice] = useState<string>("");
  const [pending, setPending] = useState<boolean>(false);
  const requestId = useRef<number>(0);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [menuError, setMenuError] = useState<string>("");
  const [menuPending, setMenuPending] = useState<boolean>(false);
  const [cart, setCart] = useState<Cart | null>(null);
  const [cartError, setCartError] = useState<string>("");
  const [cartPending, setCartPending] = useState<boolean>(false);
  const [order, setOrder] = useState<Order | null>(null);
  const confirmationId = useRef<string | null>(null);

  async function confirmCart(): Promise<void> {
    if (cart === null) return;
    setCartPending(true);
    confirmationId.current ??= crypto.randomUUID();
    try {
      const confirmed: Order = await confirmOrder(confirmationId.current, cart.revision);
      setOrder(confirmed);
      confirmationId.current = null;
      setCart(await fetchCart());
      setCartError("");
    } catch (error: unknown) {
      setCartError(error instanceof Error ? error.message : "Unable to confirm order.");
    } finally {
      setCartPending(false);
    }
  }


  useEffect(() => { void startSession().then(setCart).catch((error: unknown) => setCartError(error instanceof Error ? error.message : "Unable to start session.")); }, []);

  async function changeQuantity(itemId: string, quantity: number): Promise<void> {
    setCartPending(true);
    try {
      const next: Cart = await updateCart(itemId, quantity, crypto.randomUUID());
      setCart(next);
      setCartError("");
    } catch (error: unknown) {
      setCartError(error instanceof Error ? error.message : "Unable to update cart.");
    } finally {
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
    setMenuPending(true);
    try {
      const next: Menu = await sellOutItem(itemId);
      setMenu(next);
      setMenuError("");
      if (cart !== null) setCart(await fetchCart());
    } catch (error: unknown) {
      setMenuError(error instanceof Error ? error.message : "Unable to update the menu.");
    } finally {
      setMenuPending(false);
    }
  }

  async function restock(itemId: string): Promise<void> {
    setMenuPending(true);
    try {
      const next: Menu = await restockItem(itemId);
      setMenu(next);
      setMenuError("");
      if (cart !== null) setCart(await fetchCart());
    } catch (error: unknown) {
      setMenuError(error instanceof Error ? error.message : "Unable to restock the item.");
    } finally {
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

  return <main className="shell">
    <header className="masthead"><div className="brand"><span className="brand-mark">W</span><span>Widget lab</span></div><span className="badge">PLAYGROUND <span> / 01</span></span></header>
    <section className="intro"><p className="eyebrow">VALIDATE &amp; PREVIEW</p><h1>See your widget<br /><em>come to life.</em></h1><p>Paste a widget payload to inspect how it renders. Supports menu layout, text, badges and dividers.</p></section>
    <div className="workspace">
      <form className="panel editor" onSubmit={(event) => { void submit(event); }}>
        <div className="panel-heading"><div><span className="step">01 / INPUT</span><h2>Widget payload</h2></div><span className="format">JSON</span></div>
        <div className="example-row"><label htmlFor="example">Load an example</label><select id="example" defaultValue="welcome" onChange={(event) => setSource(examples[event.target.value])}><option value="welcome">Welcome card</option><option value="menu">Nested menu</option><option value="arabic">Arabic text</option><option value="partial">Unsupported child</option><option value="broken">Malformed JSON</option></select></div>
        <label className="source-label" htmlFor="source">Payload source</label>
        <textarea id="source" spellCheck={false} value={source} onChange={(event) => setSource(event.target.value)} aria-describedby="source-help" />
        <div className="editor-footer"><span id="source-help">Maximum source size: 32 KiB</span><button type="submit">{pending ? "Validating…" : "Validate widget"}<span aria-hidden="true"> ↗</span></button></div>
      </form>
      <section className="panel output" aria-labelledby="preview-title"><div className="panel-heading"><div><span className="step">02 / OUTPUT</span><h2 id="preview-title">Preview</h2></div><span className="live-dot">RENDER</span></div>
        <div className="preview-area" aria-busy={pending}>{card ? <Preview card={card} /> : <div className="empty-state"><span className="empty-icon" aria-hidden="true">◇</span><p>Your preview will appear here.</p><small>Validate a payload to get started.</small></div>}</div>
        <div className="diagnostics" aria-live="polite"><div className="diagnostics-heading"><h3>Validation</h3><span>{result ? result.status.toUpperCase() : "AWAITING INPUT"}</span></div>
          {notice && <p className="notice" role="alert">{notice}</p>}
          {result && result.issues.length > 0 ? <ul>{result.issues.map((item, index) => <li key={index}><strong>{item.severity}</strong><code>{item.path}</code><span>{item.message}</span></li>)}</ul> : <p className="quiet">{result ? "No issues found." : "Issues and validation details will show here."}</p>}
        </div>
      </section>
    </div>
    <section className="panel menu-panel" aria-labelledby="menu-title">
      <div className="menu-heading"><div><span className="step">RESTAURANT / المطعم</span><h2 id="menu-title">Demo menu <span lang="ar" dir="rtl"> / قائمة الطعام</span></h2></div><button type="button" onClick={() => { void refreshMenu(); }} disabled={menuPending}>Refresh menu</button></div>
      <p className="menu-help">Mock restaurant data · Mark an item sold out or restock it to try an inventory update. Refresh another tab to see the change.</p>
      {menuError && <p className="notice" role="alert">{menuError}</p>}
      {menu && <><p className="menu-revision">Menu version {menu.revision}</p><ul className="menu-list">{menu.items.map((item) => <li key={item.id}>
        <div><strong>{item.name.en}</strong><span className="menu-ar" lang="ar" dir="rtl">{item.name.ar}</span><span className="menu-price">AED {(item.price_minor / 100).toFixed(2)} · {item.available ? "Available / متوفر" : "Sold out / نفد"}</span></div>
        <div className="menu-actions"><button type="button" disabled={cartPending || cart === null || !item.available || (cart.items.find((entry) => entry.id === item.id)?.quantity ?? 0) >= 99} onClick={() => { void changeQuantity(item.id, (cart?.items.find((entry) => entry.id === item.id)?.quantity ?? 0) + 1); }}>Add to cart</button><button type="button" disabled={menuPending} onClick={() => { if (item.available) { void sellOut(item.id); } else { void restock(item.id); } }}>{item.available ? "Mark sold out" : "Restock"}</button></div>
      </li>)}</ul></>}
    </section>
    <section className="panel menu-panel" aria-labelledby="cart-title">
      <div className="menu-heading"><div><span className="step">YOUR ORDER / طلبك</span><h2 id="cart-title">Your cart</h2></div><button type="button" disabled={cartPending || cart === null} onClick={() => { void fetchCart().then(setCart).catch((error: unknown) => setCartError(error instanceof Error ? error.message : "Unable to refresh cart.")); }}>Refresh cart</button></div>
      {cartError && <p className="notice" role="alert">{cartError}</p>}
      {order && <p className="order-confirmed" role="status">Order confirmed · {order.order_id} · AED {(order.total_minor / 100).toFixed(2)}</p>}
      {cart && (cart.items.length === 0 ? <p className="menu-help">Your cart is empty.</p> : <><ul className="menu-list">{cart.items.map((item) => <li key={item.id}><div><strong>{item.name_en} <span lang="ar" dir="rtl">{item.name_ar}</span></strong><span className="menu-price">{item.quantity} × AED {(item.price_minor / 100).toFixed(2)} {!item.available && "· Sold out / نفد"}</span></div><div className="menu-actions"><button type="button" disabled={cartPending} onClick={() => { void changeQuantity(item.id, item.quantity - 1); }} aria-label={`Remove one ${item.name_en}`}>−</button><button type="button" disabled={cartPending || !item.available || item.quantity >= 99} onClick={() => { void changeQuantity(item.id, item.quantity + 1); }} aria-label={`Add one ${item.name_en}`}>+</button></div></li>)}</ul><p className="menu-help">Selected items total: AED {(cart.total_minor / 100).toFixed(2)}</p>{!cart.can_checkout && <p className="notice">A selected item is sold out. Remove it or restock it before confirming.</p>}<button type="button" disabled={cartPending || !cart.can_checkout} onClick={() => { void confirmCart(); }}>Confirm order</button></>)}
    </section>
    <footer><span>WIDGET LAB <span className="footer-slash">/</span> PAYLOAD PLAYGROUND</span><span>Built for careful experimentation.</span></footer>
  </main>;
}

const root: HTMLElement | null = document.getElementById("root");
if (root === null) throw new Error("Application root is missing.");
createRoot(root).render(<StrictMode><App /></StrictMode>);
