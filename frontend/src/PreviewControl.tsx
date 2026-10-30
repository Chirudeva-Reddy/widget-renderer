import { createContext, useContext, useId, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import type { ControlNode } from "./api";

type Drafts = Readonly<Record<string, string>>;
type DraftContext = { drafts: Drafts; setDraft: (name: string, value: string) => void };
const FormDraftContext = createContext<DraftContext | null>(null);

export function PreviewForm({ children }: { children: ReactNode }): ReactElement {
  const [drafts, setDrafts] = useState<Drafts>({});
  function setDraft(name: string, value: string): void {
    setDrafts((previous: Drafts) => ({ ...previous, [name]: value }));
  }
  return <FormDraftContext.Provider value={{ drafts, setDraft }}><fieldset className="widget-form"><legend>Form preview · actions disabled</legend>{children}</fieldset></FormDraftContext.Provider>;
}

export function PreviewControl({ control }: { control: ControlNode }): ReactElement {
  const id: string = useId();
  const context: DraftContext | null = useContext(FormDraftContext);
  const [localDraft, setLocalDraft] = useState<string | null>(null);
  if (control.kind === "button") return <button type="button" disabled title="Preview only: actions are disabled">{control.label}</button>;
  const name: string = control.name;
  const value: string = context === null ? localDraft ?? control.value : context.drafts[control.name] ?? control.value;
  function change(next: string): void {
    if (context === null) setLocalDraft(next);
    else context.setDraft(name, next);
  }
  if (control.kind === "input") return <label className="widget-field" htmlFor={id}><span>{control.name}</span><input id={id} name={control.name} type="number" min="0" max="99" step="1" value={value} onChange={(event) => change(event.target.value)} placeholder={control.placeholder} required={control.required} disabled={control.disabled} /></label>;
  const unavailable: boolean = value !== "" && !control.options.some((option) => option.value === value && !option.disabled);
  return <label className="widget-field" htmlFor={id}><span>{control.name}</span><select id={id} name={control.name} value={value} onChange={(event) => change(event.target.value)} disabled={control.disabled} aria-invalid={unavailable} aria-describedby={unavailable ? `${id}-notice` : undefined}><option value="" disabled>{control.placeholder || "Select an option"}</option>{unavailable && !control.options.some((option) => option.value === value) && <option value={value} disabled>{value} · unavailable</option>}{control.options.map((option) => <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}</select>{unavailable && <span id={`${id}-notice`} role="status">Your previous selection is unavailable. Choose another option.</span>}</label>;
}
