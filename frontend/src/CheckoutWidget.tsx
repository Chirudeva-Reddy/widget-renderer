import type { ReactElement } from "react";
import type { Cart, Order, CheckoutView, Card } from "./api";

type Locale = "en" | "ar";

function OrderLines({ items, locale }: { items: Cart["items"]; locale: Locale }): ReactElement {
  return <ul className="checkout-lines">{items.map((item) => <li key={item.id}>
    <div className="checkout-line-main"><span className="checkout-line-tile" aria-hidden="true">{item.quantity}</span><div><strong>{locale === "ar" ? item.name_ar : item.name_en}</strong><span className="checkout-unit"><bdi>{item.quantity} × AED {(item.price_minor / 100).toFixed(2)}</bdi></span></div><strong className="checkout-line-total"><bdi>AED {(item.quantity * item.price_minor / 100).toFixed(2)}</bdi></strong></div>
    {!item.available && <span className="notice">{locale === "ar" ? "نفد هذا الصنف. عدّل الطلب لإزالته." : "Sold out. Edit your order to remove this item."}</span>}
  </li>)}</ul>;
}

type ReviewProps = {
  invalidated: boolean; view: CheckoutView; renderCard: (card: Card) => ReactElement; cart: Cart; reviewedRevision: string; locale: Locale; disabled: boolean; hasDrafts: boolean; error: string;
  onEdit: () => void; onReview: () => void; onConfirm: () => void;
};

export function OrderReview({ invalidated, view, renderCard, cart, reviewedRevision, locale, disabled, hasDrafts, error, onEdit, onReview, onConfirm }: ReviewProps): ReactElement {
  const arabic: boolean = locale === "ar";
  const stale: boolean = invalidated || cart.revision !== reviewedRevision;
  return <section className="widget-card checkout-card" aria-label={arabic ? "مراجعة الطلب" : "Order review"} lang={locale} dir={arabic ? "rtl" : "ltr"}>
    {renderCard(view.payload[locale])}
    {!cart.can_checkout && cart.items.length > 0 && <p className="notice" role="status">{arabic ? "أزل الأصناف غير المتوفرة قبل تأكيد الطلب." : "Remove sold-out items before confirming your order."}</p>}
    {stale && <div className="notice" role="status"><p>{arabic ? "تغيرت السلة أو حالة التوفر. راجع الطلب المحدّث قبل التأكيد." : "Your cart or availability changed. Review the updated order before confirming."}</p><button type="button" disabled={disabled || hasDrafts} onClick={onReview}>{arabic ? "مراجعة الطلب المحدّث" : "Review updated order"}</button></div>}
    {hasDrafts && <p className="notice">{arabic ? "طبّق الكميات المدخلة قبل التأكيد." : "Apply your entered quantities before confirming."}</p>}
    {disabled && <p className="notice" role="status">{arabic ? "انتظر اكتمال التحديثات المباشرة قبل المتابعة." : "Wait for live updates and pending changes before continuing."}</p>}
    {error && <p className="notice" role="alert">{error}</p>}
    <div className="checkout-actions"><button type="button" disabled={disabled} onClick={onEdit}>{arabic ? "تعديل الطلب" : "Edit order"}</button><button type="button" disabled={disabled || stale || hasDrafts || !cart.can_checkout} onClick={onConfirm}>{arabic ? "تأكيد الطلب" : "Confirm order"}</button></div>
  </section>;
}

export function ConfirmationRecovery({ locale, disabled, error, onRetry }: { locale: Locale; disabled: boolean; error: string; onRetry: () => void }): ReactElement {
  const arabic: boolean = locale === "ar";
  return <section className="widget-card checkout-card" aria-label={arabic ? "استرجاع تأكيد الطلب" : "Confirmation recovery"} lang={locale} dir={arabic ? "rtl" : "ltr"}>
    <h3>{arabic ? "استرجاع نتيجة التأكيد" : "Retrieve confirmation result"}</h3>
    <p>{arabic ? "قد يكون الطلب قد تأكد بالفعل. أعد المحاولة لاسترجاع النتيجة بنفس الطلب الأصلي." : "Your order may already be confirmed. Retry to retrieve the result using the original request."}</p>
    {error && <p className="notice" role="alert">{error}</p>}
    <button type="button" disabled={disabled} onClick={onRetry}>{arabic ? "إعادة المحاولة واسترجاع النتيجة" : "Retry confirmation / retrieve result"}</button>
  </section>;
}

export function OrderReceipt({ order, locale, disabled, onStart }: { order: Order; locale: Locale; disabled: boolean; onStart: () => void }): ReactElement {
  const arabic: boolean = locale === "ar";
  return <section className="widget-card checkout-card" aria-label={arabic ? "إيصال الطلب" : "Order receipt"} lang={locale} dir={arabic ? "rtl" : "ltr"}>
    <h3 role="status">{arabic ? "تم تأكيد الطلب" : "Order confirmed"} · <bdi>{order.order_id}</bdi></h3>
    <OrderLines items={order.items} locale={locale} />
    <p>{arabic ? "الإجمالي" : "Total"}: <bdi>AED {(order.total_minor / 100).toFixed(2)}</bdi></p>
    {disabled && <p className="notice" role="status">{arabic ? "جارٍ مزامنة السلة قبل بدء طلب آخر." : "Synchronizing your cart before starting another order."}</p>}
    <button type="button" disabled={disabled} onClick={onStart}>{arabic ? "بدء طلب آخر" : "Start another order"}</button>
  </section>;
}
