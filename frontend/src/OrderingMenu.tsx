import type { FormEvent, ReactElement } from "react";
import type { Card, Cart, Menu, Node } from "./api";

export type QuantityEdit = { value: string; cartRevision: string; actionId: string };
export type CartChange = { itemId: string; quantity: number; cartRevision: string; actionId: string };
type QuantityEditorProps = {
  item: Menu["items"][number]; cart: Cart; locale: "en" | "ar"; disabled: boolean;
  edit: QuantityEdit | null; setEdit: (edit: QuantityEdit | null) => void;
  onChange: (change: CartChange) => Promise<boolean>;
};

function QuantityEditor({ item, cart, locale, disabled, edit, setEdit, onChange }: QuantityEditorProps): ReactElement {
  const quantity: number = cart.items.find((entry) => entry.id === item.id)?.quantity ?? 0;
  const value: string = edit?.value ?? String(quantity);
  const stale: boolean = edit !== null && edit.cartRevision !== cart.revision;
  const maximum: number = item.available ? 99 : quantity;
  const valid: boolean = /^[0-9]{1,2}$/.test(value) && Number(value) <= maximum;
  const arabic: boolean = locale === "ar";

  async function save(next: QuantityEdit): Promise<void> {
    setEdit(next);
    const success: boolean = await onChange({ itemId: item.id, quantity: Number(next.value), cartRevision: next.cartRevision, actionId: next.actionId });
    if (success) setEdit(null);
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (disabled || stale || !valid || edit === null) return;
    void save(edit);
  }

  return <form className="quantity-editor" onSubmit={submit}>
    <button type="button" className="quantity-step" aria-label={`${arabic ? "تقليل" : "Decrease"} ${item.name[locale]}`} disabled={disabled || stale || edit !== null || quantity === 0} onClick={() => { void save({ value: String(quantity - 1), cartRevision: cart.revision, actionId: crypto.randomUUID() }); }}>−</button>
    <label><span>{arabic ? "الكمية" : "Quantity"} · {item.name[locale]}</span>
      <input type="number" min="0" max={maximum} step="1" required value={value} disabled={disabled}
        onChange={(event) => setEdit({ value: event.target.value, cartRevision: edit?.cartRevision ?? cart.revision, actionId: crypto.randomUUID() })} />
    </label>
    <button type="button" className="quantity-step" aria-label={`${arabic ? "زيادة" : "Increase"} ${item.name[locale]}`} disabled={disabled || stale || edit !== null || !item.available || quantity >= 99} onClick={() => { void save({ value: String(quantity + 1), cartRevision: cart.revision, actionId: crypto.randomUUID() }); }}>+</button>
    <button type="submit" disabled={disabled || stale || !valid || edit === null}>{arabic ? "تطبيق" : "Apply"}</button>
    <button type="button" disabled={disabled || stale || quantity === 0} onClick={() => { void save({ value: "0", cartRevision: cart.revision, actionId: crypto.randomUUID() }); }}>{arabic ? "إزالة" : "Remove"}</button>
    {!item.available && <p className="notice">{arabic ? "نفد هذا الصنف. يمكنك تقليل الكمية أو إزالته." : "Sold out. You can reduce the quantity or remove this item."}</p>}
    {!valid && <p className="notice" role="alert">{arabic ? `أدخل كمية صحيحة من 0 إلى ${maximum}.` : `Enter a whole quantity from 0 to ${maximum}.`}</p>}
    {stale && <div className="notice"><p>{arabic ? `تغيرت السلة. الكمية الحالية: ${quantity}. راجعها قبل تطبيق القيمة المدخلة.` : `Your cart changed. Current quantity: ${quantity}. Review it before applying your entered value.`}</p><button type="button" disabled={disabled} onClick={() => setEdit({ value, cartRevision: cart.revision, actionId: crypto.randomUUID() })}>{arabic ? "مراجعة أحدث سلة" : "Review latest cart"}</button></div>}
  </form>;
}

type OrderingMenuProps = {
  menu: Menu; cart: Cart; card: Card; locale: "en" | "ar"; disabled: boolean; error: string;
  edits: Readonly<Record<string, QuantityEdit>>; onEdit: (itemId: string, edit: QuantityEdit | null) => void; onReview: () => void;
  onChange: (change: CartChange) => Promise<boolean>; renderNode: (node: Node) => ReactElement;
};

export function OrderingMenu({ menu, cart, card, locale, disabled, error, edits, onEdit, onReview, onChange, renderNode }: OrderingMenuProps): ReactElement {
  if (card.kind !== "list" || card.children.length !== menu.items.length) throw new Error("The ordering menu does not match its authoritative dish rows.");
  return <div className="ordering-menu">
    <div className="ordering-header"><strong>{locale === "ar" ? "قائمة الطعام" : "Order food"}</strong><span>{locale === "ar" ? "اختر أصنافك" : "Choose your dishes"}</span></div>
    {menu.items.map((item, index) => <div className="ordering-item" key={item.id}>
      {renderNode(card.children[index])}
      <QuantityEditor item={item} cart={cart} locale={locale} disabled={disabled} edit={edits[item.id] ?? null} setEdit={(edit: QuantityEdit | null) => onEdit(item.id, edit)} onChange={onChange} />
    </div>)}
    <p>{locale === "ar" ? "إجمالي الأصناف المختارة" : "Selected items total"}: <bdi>AED {(cart.total_minor / 100).toFixed(2)}</bdi></p>
    {Object.keys(edits).length > 0 && <p className="notice">{locale === "ar" ? "طبّق الكميات المدخلة قبل مراجعة الطلب." : "Apply your entered quantities before reviewing the order."}</p>}
    <button type="button" disabled={disabled || cart.items.length === 0 || Object.keys(edits).length > 0} onClick={onReview}>{locale === "ar" ? "مراجعة الطلب" : "Review order"}</button>
    {error && <p className="notice" role="alert">{error}</p>}
  </div>;
}
