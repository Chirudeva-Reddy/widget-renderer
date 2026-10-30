import { useId } from "react";
import type { ReactElement } from "react";
import type { ControlNode } from "./api";

export function PreviewControl({ control }: { control: ControlNode }): ReactElement {
  const id: string = useId();
  if (control.kind === "button") return <button type="button" disabled title="Preview only: actions are disabled">{control.label}</button>;
  if (control.kind === "input") return <label className="widget-field" htmlFor={id}><span>{control.name}</span><input id={id} name={control.name} type="number" min="0" max="99" step="1" defaultValue={control.value} placeholder={control.placeholder} required={control.required} disabled={control.disabled} /></label>;
  return <label className="widget-field" htmlFor={id}><span>{control.name}</span><select id={id} name={control.name} defaultValue={control.value} disabled={control.disabled}><option value="" disabled>{control.placeholder || "Select an option"}</option>{control.options.map((option) => <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}</select></label>;
}
