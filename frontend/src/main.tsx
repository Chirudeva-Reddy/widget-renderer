import { StrictMode, useRef, useState } from "react";
import type { FormEvent, ReactElement } from "react";
import { createRoot } from "react-dom/client";
import { validatePayload } from "./api";
import type { Card, Node, ValidationResult } from "./api";
import "./style.css";

const examples: Record<string, string> = {
  welcome: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "Welcome! What would you like to order?" }, { type: "Text", value: "Choose from the menu to get started." }] }, null, 2),
  menu: JSON.stringify({ type: "ListView", children: [{ type: "ListViewItem", children: [{ type: "Row", children: [{ type: "Text", value: "Hummus" }, { type: "Text", value: "$8.50" }] }] }, { type: "ListViewItem", children: [{ type: "Text", value: "Falafel" }] }] }, null, 2),
  arabic: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "مرحباً! ماذا تود أن تطلب؟" }] }, null, 2),
  partial: JSON.stringify({ type: "Card", children: [{ type: "Text", value: "This item is available." }, { type: "Unknown" }, { type: "Text", value: "This item is available too." }] }, null, 2),
  broken: '{ "type": "Card", "children": [',
};

function PreviewNode({ node }: { node: Node }): ReactElement {
  if (node.kind === "text") return <p className="widget-text" dir="auto">{node.value}</p>;
  if (node.kind === "problem") return <p className="problem">{node.message}</p>;
  return <div className={`widget-${node.kind}`}>
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
    <section className="intro"><p className="eyebrow">VALIDATE &amp; PREVIEW</p><h1>See your widget<br /><em>come to life.</em></h1><p>Paste a widget payload to inspect how it renders. Supports Card, ListView, Row, Col and Text.</p></section>
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
    <footer><span>WIDGET LAB <span className="footer-slash">/</span> PAYLOAD PLAYGROUND</span><span>Built for careful experimentation.</span></footer>
  </main>;
}

const root: HTMLElement | null = document.getElementById("root");
if (root === null) throw new Error("Application root is missing.");
createRoot(root).render(<StrictMode><App /></StrictMode>);
