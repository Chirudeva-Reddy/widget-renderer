import { createContext, useContext, useId, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import type { ControlNode } from "./api";

type Drafts = Readonly<Record<string, string>>;
type DraftContext = { drafts: Drafts; setDraft: (name: string, value: string) => void; active: boolean };
const FormDraftContext = createContext<DraftContext | null>(null);
type DraftStore = { drafts: Drafts; setDraft: (key: string, value: string) => void };
const WidgetDraftContext = createContext<DraftStore | null>(null);

export function WidgetDraftProvider({ children }: { children: ReactNode }): ReactElement {
  const [drafts, setDrafts] = useState<Drafts>({});
  function setDraft(key: string, value: string): void { setDrafts((previous) => ({ ...previous, [key]: value })); }
  return <WidgetDraftContext.Provider value={{ drafts, setDraft }}>{children}</WidgetDraftContext.Provider>;
}

export function PreviewForm({ children, disabled, onSubmit, scope }: { children: ReactNode; disabled: boolean; scope: string | null; onSubmit: ((quantity: string) => void) | null }): ReactElement {
  const [localDrafts, setDrafts] = useState<Drafts>({});
  const store: DraftStore | null = useContext(WidgetDraftContext);
  const prefix: string = `form:${scope}:`;
  const drafts: Drafts = store !== null && scope !== null ? Object.fromEntries(Object.entries(store.drafts).filter(([key]) => key.startsWith(prefix)).map(([key, value]) => [key.slice(prefix.length), value])) : localDrafts;
  function setDraft(name: string, value: string): void {
    if (store !== null && scope !== null) store.setDraft(`${prefix}${name}`, value);
    else setDrafts((previous: Drafts) => ({ ...previous, [name]: value }));
  }
  return <FormDraftContext.Provider value={{ drafts, setDraft, active: onSubmit !== null }}><form onSubmit={(event) => { event.preventDefault(); const value = new FormData(event.currentTarget).get("quantity"); if (onSubmit !== null && typeof value === "string") onSubmit(value); }}><fieldset disabled={disabled} className="widget-form"><legend>{onSubmit === null ? "Form preview · actions disabled" : "Quantity"}</legend>{children}</fieldset></form></FormDraftContext.Provider>;
}

export function PreviewControl({ control, disabled, onChange }: { control: ControlNode; disabled: boolean; onChange: ((value: string) => void) | null }): ReactElement {
  const id: string = useId();
  const context: DraftContext | null = useContext(FormDraftContext);
  const store: DraftStore | null = useContext(WidgetDraftContext);
  const [localDraft, setLocalDraft] = useState<string | null>(null);
  if (control.kind === "button") return <button type={context?.active ? "submit" : "button"} disabled={control.disabled === true || disabled || !context?.active}>{control.label}</button>;
  const name: string = control.name;
  const fieldKey: string = `field:${control.key ?? name}`;
  const value: string = context === null ? (store !== null && Object.hasOwn(store.drafts, fieldKey) ? store.drafts[fieldKey] : localDraft ?? control.value) : (Object.hasOwn(context.drafts, control.name) ? context.drafts[control.name] : control.value);
  function change(next: string): void {
    if (context === null && store !== null) store.setDraft(fieldKey, next);
    else if (context === null) setLocalDraft(next);
    else context.setDraft(name, next);
    if (onChange !== null) onChange(next);
  }
  if (control.kind === "input") return <label className="widget-field" htmlFor={id}><span>{control.name}</span><input id={id} name={control.name} type="number" min="0" max="99" step="1" value={value} onChange={(event) => change(event.target.value)} placeholder={control.placeholder} required={control.required} disabled={control.disabled || disabled} /></label>;
  const unavailable: boolean = value !== "" && !control.options.some((option) => option.value === value && !option.disabled);
  return <label className="widget-field" htmlFor={id}><span>{control.name}</span><select id={id} name={control.name} value={value} onChange={(event) => change(event.target.value)} disabled={control.disabled || disabled} aria-invalid={unavailable} aria-describedby={unavailable ? `${id}-notice` : undefined}><option value="" disabled>{control.placeholder || "Select an option"}</option>{unavailable && !control.options.some((option) => option.value === value) && <option value={value} disabled>{value} · unavailable</option>}{control.options.map((option) => <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}</select>{unavailable && <span id={`${id}-notice`} role="status">Your previous selection is unavailable. Choose another option.</span>}</label>;
}
