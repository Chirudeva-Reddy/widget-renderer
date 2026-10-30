# ChatKit widget examples — scraped reference for the food-ordering renderer

Scraped 2026-10-30 from https://widgets.chatkit.studio. Sources:

- **Gallery** (`/gallery`): 19 built-in examples. The compiled JSON was read from the live React tree, so it is exactly what the ChatKit renderer receives.
- **Component spec**: the Studio bundle (`assets/index-*.js`) includes the system prompt Studio uses to generate widgets, with the full TypeScript prop reference for all 30 components. The prop reference is copied verbatim to [chatkit-components.d.ts](chatkit-components.d.ts). Treat that file as the source of truth for prop names, enums and defaults.
- **Our own widgets** (`03-widget-renderer/widget-example/*.widget.json`): Food Menu and Order Confirmation in EN and AR. The compiled menu JSON below came from the Studio editor.

Not scraped: the weather, flight, player, playlist, ride, calendar and email gallery cards. They add no component or pattern that the examples below don't already show (§6 has a summary of them).

---

## 1. Two formats: what you author vs. what you render

A `.widget` file is an **authoring template**. The renderer only ever sees the **compiled JSON tree**.

| | `.widget` file (authoring) | Wire payload (renderer input) |
|---|---|---|
| Shape | `{ id, name, view, defaultState, states, schema, jsonSchema, schemaMode }` | `{ type: "Card" \| "ListView" \| "Basic", ...props, children: [...] }` |
| `view` | JSX-like template string with `{expr}`, `.map()`, `cond && <X/>` | — (resolved away) |
| Data | `defaultState` object, validated by a zod `schema` (string) | inlined into prop values |

### Compile rules (seen by comparing views with their JSON)

1. `<Comp a="x" b={1}>…</Comp>` compiles to `{ "type": "Comp", "a": "x", "b": 1, "children": [ … ] }`. `children` is left out when the component has none.
2. **Text is never a child.** Text, Title, Caption, Badge, Button, Label and Markdown carry their text in `value` or `label`.
3. A false `{cond && <X/>}` disappears entirely, with no null placeholder. A true one is inlined.
4. `{items.map(...)}` is flattened into the parent's `children`. **`key` is kept** as a plain prop (`"key": "shawarma"`). This is the stable identity you need for in-place updates.
5. A bare boolean attribute (`flush`, `block`, `submit`) compiles to `true`.
6. Template literals are resolved: ``label={`${item.qty}`}`` becomes `"label": "1"`. Numbers often reach you as strings.
7. Sub-components keep the dot: `"Table.Row"` and `"Table.Cell"` (the runtime registers exactly these names; it also registers an undocumented `"Grid.Item"`).
8. Action objects (`onClickAction`, `onSubmitAction`, `confirm.action`) pass through unchanged, with their `payload` already resolved.

---

## 2. Component catalogue (condensed from chatkit-components.d.ts)

**Roots:** `Card`, `ListView`, `Basic`. Use Card for one thing (a summary, confirmation or form). Use ListView for a set of options. `ListViewItem` may only appear as a direct child of `ListView`.

| type | required | notable props (default) |
|---|---|---|
| **Card** | children | `size` sm 360 / md 440 / lg 560 / full (`sm`), `padding` (4), `background`, `border`, `theme` light\|dark, `status {text, icon\|favicon}`, `collapsed`, `asForm`, `confirm {label, action}`, `cancel {label, action}` |
| **ListView** | children (ListViewItem only) | `limit` number\|"auto" (shows "Show more" past the limit), `status`, `theme` |
| **ListViewItem** | children | `onClickAction`, `gap`, `align` (`center`). Extends Row |
| **Basic** | children | `gap padding align justify direction theme` |
| Box / Row / Col | — | `direction` (Box: col), `align` (Row: center), `justify`, `wrap`, `flex`, `gap`, `padding`, `border`, `background`, plus BlockProps (`width height size min*/max* aspectRatio radius margin`) |
| Form | — | Box props + `onSubmitAction`. Collects every named control inside it |
| Spacer | — | `minSize` |
| Divider | — | `color` default\|subtle\|strong, `size` (1), `spacing`, `flush` |
| **Table** | — | children: `Table.Row` |
| Table.Row | — | `header` bool, children: `Table.Cell` |
| Table.Cell | — | `width padding colSpan rowSpan align vAlign` (start\|center\|end), `colSize` xs–xl |
| Transition | children (one component) | animates swaps; children need distinct `key` |
| **Text** | value | `size` xs–xl (md), `weight` (normal), `color`, `italic`, `lineThrough`, `width`, `minLines`, `textAlign` start\|center\|end, `truncate`, `maxLines`, `streaming`, `editable {name, required, placeholder, pattern, autoFocus, autoSelect}` |
| Title | value | `size` sm–5xl (md), `weight` (medium), `color` (prose) |
| Caption | value | `size` sm\|md\|lg, `color` (secondary) |
| Markdown | value | `streaming` |
| **Badge** | label | `color` secondary\|success\|danger\|warning\|info\|discovery, `variant` solid\|soft\|outline (soft), `size` sm\|md\|lg, `pill` (true) |
| Icon | name (fixed enum, ~55 names) | `color`, `size` xs–3xl |
| Image | src | `alt frame fit position flush` + BlockProps |
| **Button** | — | `label`, `onClickAction`, `submit`, `iconStart/iconEnd`, `style` primary\|secondary, `color`, `variant` solid\|soft\|outline\|ghost, `size` 3xs–3xl (lg), `pill` (true), `uniform`, `block`, `disabled` |
| Input | name | `inputType`, `defaultValue`, `placeholder`, `required`, `pattern`, `variant`, `size`, `disabled` |
| Textarea | name | `defaultValue rows autoResize maxRows required placeholder` |
| **Select** | name, options `[{value,label,disabled?,description?}]` | `defaultValue`, `placeholder`, `onChangeAction`, `variant`, `clearable`, `block`, `disabled` |
| DatePicker | name | `defaultValue` (ISO), `min`, `max`, `onChangeAction`, `clearable`, `variant` |
| Checkbox | name | `label`, `defaultChecked`, `onChangeAction`, `required` |
| RadioGroup | name | `options`, `defaultValue`, `direction` (row), `onChangeAction`, `required` |
| Label | value, fieldName | `size weight textAlign color` |
| **Chart** | data, series, xAxis | `showYAxis` (false), `showLegend` (true), `barGap`, `barCategoryGap`, `height/width/aspectRatio…`. The d.ts lists `showLegend` twice; the second one is documented as "tooltip". Ignore unknown keys |

**Chart series:** `{ type: "bar"|"line"|"area", dataKey, label?, color?, stack? (bar/area), curveType? (line/area, default "natural") }`.
**xAxis:** `{ dataKey, hide?, labels?: { rawValue: "Display" } }`.

### Tokens

- **Text colours:** `prose primary emphasis secondary tertiary success warning danger`, plus `alpha-NN` (alpha-50, alpha-70 seen)
- **Surface / background:** `surface surface-secondary surface-tertiary surface-elevated surface-elevated-secondary`
- **Border colours:** `default subtle strong`
- **Primitive colours:** Tailwind-like `red-400`, `blue-100`, `green-400`, `white`
- **Chart colours:** `blue purple orange green red yellow pink`
- Any colour may also be `{ light, dark }`, a hex value (`#FF7B00`) or a raw CSS string. The gallery uses `linear-gradient(...)` and `url(...) no-repeat center / cover` as Card `background`, so **sanitise CSS strings**.
- **Spacing:** unitless numbers are spacing units (decimals are allowed, e.g. `1.1`). Strings are CSS (`"40px"`, `"30%"`). Padding can be an object `{x, y, top, right, bottom, left}`.
- **Radius:** `2xs xs sm md lg xl 2xl 3xl 4xl full 100% none`

---

## 3. Interaction contract

```ts
type ActionConfig = {
  type: string                         // e.g. "cart.add"
  payload?: Record<string, unknown>
  handler?: "server" | "client"
  loadingBehavior?: "auto" | "none" | "self" | "container"
}
```

Where actions come from:

- `Button.onClickAction` and `ListViewItem.onClickAction` (clicking the whole row)
- `Card.confirm.action` and `Card.cancel.action`: footer buttons. With `asForm`, they also capture form data.
- `Form.onSubmitAction`: fired by `<Button submit>`. The payload gains the values of every named control.
- `Select / DatePicker / Checkbox / RadioGroup .onChangeAction`
- `Text.editable.name`: makes the Text an inline input that joins the form payload.
- Field `name` supports dot paths: `"purchase.volume"` becomes `payload.purchase.volume`.

From the spec's "common mistakes" list: a missing `name` means no form data. Invented props are silently ignored. A missing `key` on mapped rows means lost focus on re-render. Confirm with invalid required fields does not fire. Unknown icon names render nothing.

How the spec describes updates: *"a user action posts a message; the server responds with a new widget as a replacement, the client gracefully transitions between the old and new UI tree."* Components that own local state (ListView's show-more, Select, Input) must keep that state across the replacement, keyed by `key` and `name`.

### Patterns already in our own widgets (keep them)

- `payload.version`: a widget state version. The agent can reject actions sent from a stale render.
- `payload.position: i + 1`: the on-screen index. This is how "the second one" resolves to what the user actually saw.
- `loadingBehavior: "self"` on +/− and `"container"` on checkout and locale: disable the control (or the whole widget) while the request is in flight, which is our double-tap guard.
- `disabled: !item.available`: a sold-out item can't be added, but `−` stays enabled so the user can remove it.

---

## 4. Our scenario — exact payloads

### 4a. Food menu (ListView), compiled by Studio from `menu-en.widget.json`

The state is the editor's saved copy, so the subtotal differs from `defaultState`. Note that Tabbouleh is sold out but still has qty 1 in the cart.

```json
{
  "type": "ListView", "limit": 5,
  "children": [
    { "type": "ListViewItem", "key": "header", "align": "center", "gap": 2, "children": [
      { "type": "Title", "value": "Order food", "size": "md" },
      { "type": "Spacer" },
      { "type": "Row", "gap": 1, "children": [
        { "type": "Button", "label": "EN", "size": "sm", "variant": "solid",
          "onClickAction": { "type": "locale.set", "payload": { "lang": "en", "version": 4 }, "handler": "server", "loadingBehavior": "container" } },
        { "type": "Button", "label": "عربي", "size": "sm", "variant": "outline",
          "onClickAction": { "type": "locale.set", "payload": { "lang": "ar", "version": 4 }, "handler": "server", "loadingBehavior": "container" } }
      ]}
    ]},
    { "type": "ListViewItem", "key": "shawarma", "align": "center", "gap": 3, "children": [
      { "type": "Col", "gap": 1, "flex": 1, "children": [
        { "type": "Text", "value": "Chicken Shawarma", "size": "sm", "weight": "semibold", "color": "prose" },
        { "type": "Row", "gap": 2, "align": "center", "children": [ { "type": "Caption", "value": "$8.50" } ] }
      ]},
      { "type": "Row", "gap": 1, "align": "center", "children": [
        { "type": "Button", "label": "−", "size": "sm", "variant": "outline", "disabled": false,
          "onClickAction": { "type": "cart.remove", "payload": { "id": "shawarma", "position": 1, "version": 4 }, "handler": "server", "loadingBehavior": "self" } },
        { "type": "Badge", "label": "1", "variant": "outline" },
        { "type": "Button", "label": "+", "size": "sm", "style": "primary", "disabled": false,
          "onClickAction": { "type": "cart.add", "payload": { "id": "shawarma", "position": 1, "version": 4 }, "handler": "server", "loadingBehavior": "self" } }
      ]}
    ]},
    { "type": "ListViewItem", "key": "falafel", "align": "center", "gap": 3, "children": [
      { "type": "Col", "gap": 1, "flex": 1, "children": [
        { "type": "Text", "value": "Falafel Plate", "size": "sm", "weight": "semibold", "color": "prose" },
        { "type": "Row", "gap": 2, "align": "center", "children": [ { "type": "Caption", "value": "$7.00" } ] }
      ]},
      { "type": "Row", "gap": 1, "align": "center", "children": [
        { "type": "Button", "label": "−", "size": "sm", "variant": "outline", "disabled": false,
          "onClickAction": { "type": "cart.remove", "payload": { "id": "falafel", "position": 2, "version": 4 }, "handler": "server", "loadingBehavior": "self" } },
        { "type": "Badge", "label": "2", "variant": "outline" },
        { "type": "Button", "label": "+", "size": "sm", "style": "primary", "disabled": false,
          "onClickAction": { "type": "cart.add", "payload": { "id": "falafel", "position": 2, "version": 4 }, "handler": "server", "loadingBehavior": "self" } }
      ]}
    ]},
    { "type": "ListViewItem", "key": "tabbouleh", "align": "center", "gap": 3, "children": [
      { "type": "Col", "gap": 1, "flex": 1, "children": [
        { "type": "Text", "value": "Tabbouleh", "size": "sm", "weight": "semibold", "color": "tertiary" },
        { "type": "Row", "gap": 2, "align": "center", "children": [
          { "type": "Caption", "value": "$5.50" },
          { "type": "Badge", "label": "Sold out", "color": "danger", "variant": "soft", "size": "sm" }
        ]}
      ]},
      { "type": "Row", "gap": 1, "align": "center", "children": [
        { "type": "Button", "label": "−", "size": "sm", "variant": "outline", "disabled": false,
          "onClickAction": { "type": "cart.remove", "payload": { "id": "tabbouleh", "position": 3, "version": 4 }, "handler": "server", "loadingBehavior": "self" } },
        { "type": "Badge", "label": "1", "variant": "outline" },
        { "type": "Button", "label": "+", "size": "sm", "style": "primary", "disabled": true,
          "onClickAction": { "type": "cart.add", "payload": { "id": "tabbouleh", "position": 3, "version": 4 }, "handler": "server", "loadingBehavior": "self" } }
      ]}
    ]},
    { "type": "ListViewItem", "key": "footer", "children": [
      { "type": "Col", "gap": 2, "flex": 1, "children": [
        { "type": "Row", "align": "center", "children": [
          { "type": "Text", "value": "Subtotal", "size": "sm", "color": "secondary" },
          { "type": "Spacer" },
          { "type": "Text", "value": "$28.00", "size": "sm", "weight": "semibold" }
        ]},
        { "type": "Button", "label": "Checkout", "style": "primary", "block": true, "disabled": false,
          "onClickAction": { "type": "checkout.start", "payload": { "version": 4 }, "handler": "server", "loadingBehavior": "container" } }
      ]}
    ]}
  ]
}
```

### 4b. Order confirmation (Card), compiled by hand from `confirm-en.widget.json` using the §1 rules

```json
{
  "type": "Card", "size": "md",
  "children": [
    { "type": "Row", "align": "center", "children": [
      { "type": "Title", "value": "Confirm your order", "size": "md" },
      { "type": "Spacer" },
      { "type": "Caption", "value": "ORD-1042" }
    ]},
    { "type": "Text", "value": "Tabbouleh sold out and was removed.", "size": "sm", "color": "danger", "textAlign": "start" },
    { "type": "Divider", "flush": true },
    { "type": "Col", "gap": 2, "children": [
      { "type": "Row", "key": "shawarma", "gap": 2, "align": "center", "children": [
        { "type": "Badge", "label": "1×", "variant": "outline" },
        { "type": "Text", "value": "Chicken Shawarma", "size": "sm" },
        { "type": "Spacer" },
        { "type": "Text", "value": "$8.50", "size": "sm" }
      ]},
      { "type": "Row", "key": "falafel", "gap": 2, "align": "center", "children": [
        { "type": "Badge", "label": "2×", "variant": "outline" },
        { "type": "Text", "value": "Falafel Plate", "size": "sm" },
        { "type": "Spacer" },
        { "type": "Text", "value": "$14.00", "size": "sm" }
      ]}
    ]},
    { "type": "Divider", "flush": true },
    { "type": "Row", "align": "center", "children": [
      { "type": "Text", "value": "Total", "size": "sm", "weight": "semibold" },
      { "type": "Spacer" },
      { "type": "Text", "value": "$22.50", "size": "sm", "weight": "semibold" }
    ]},
    { "type": "Row", "gap": 2, "justify": "start", "children": [
      { "type": "Button", "label": "Place order", "style": "primary",
        "onClickAction": { "type": "order.confirm", "payload": { "order_id": "ORD-1042", "version": 6 }, "handler": "server", "loadingBehavior": "container" } },
      { "type": "Button", "label": "Edit order", "variant": "outline",
        "onClickAction": { "type": "order.edit", "payload": { "order_id": "ORD-1042", "version": 6 }, "handler": "server", "loadingBehavior": "container" } }
    ]}
  ]
}
```

### 4c. Arabic: the renderer owns mirroring (decided; also SPEC.md §RTL and review finding 18)

The renderer mirrors through `dir="rtl"` and logical CSS. **A payload uses one child order for both languages**: the order in 4a/4b. An Arabic payload is the same tree with Arabic strings, so the agent never reverses children.

The supplied templates mirror by hand. All four files share one `view`, and its `lang === "ar"` branches reorder children: the title after the Spacer, the total before its label, the Badge last, and `justify="end"`. Do not copy those branches. Under `dir="rtl"` they would flip twice and come out left to right. Only the template's `defaultState` strings (labels, dish names, notice) carry over. The originals in `03-widget-renderer/widget-example/` are left unchanged as source material.

Arabic confirmation header and line, in canonical order (compare 4b):

```json
{ "type": "Card", "size": "md", "children": [
  { "type": "Row", "align": "center", "children": [
    { "type": "Title", "value": "تأكيد الطلب", "size": "md" },
    { "type": "Spacer" },
    { "type": "Caption", "value": "ORD-1042" }
  ]},
  { "type": "Text", "value": "نفدت التبولة وأُزيلت من طلبك.", "size": "sm", "color": "danger", "textAlign": "start" },
  { "type": "Row", "key": "shawarma", "gap": 2, "align": "center", "children": [
    { "type": "Badge", "label": "1×", "variant": "outline" },
    { "type": "Text", "value": "شاورما دجاج", "size": "sm" },
    { "type": "Spacer" },
    { "type": "Text", "value": "$8.50", "size": "sm" }
  ]}
]}
```

Renderer rules that follow:
- `textAlign`, `align` and `justify` already use logical values (`start`/`end`), so they flip with `dir` without any changes.
- Wrap each text value in bidi isolation (`<bdi>` or `unicode-bidi: isolate`). That keeps `$8.50`, `ORD-1042`, `1×` and English dish names inside Arabic text readable.
- Charts don't mirror (SPEC.md line 66). Render the plot area with `dir="ltr"` and translate only the labels.
- The locale toggle keeps `[EN, عربي]` in one order and marks the active button with `variant: "solid"`.

---

## 5. Gallery payloads relevant to our task

All of these have `"size": "lg"` on the root Card. The gallery forces that for display; the source templates use `sm`/`md`.

### purchase_items: line items, totals and two actions (closest to an order summary)

```json
{ "type": "Card", "size": "lg", "children": [
  { "type": "Col", "children": [
    { "type": "Row", "key": "Black Sugar Hoick Latte", "align": "center", "children": [
      { "type": "Image", "src": "https://cdn.openai.com/API/storybook/blacksugar.png", "size": 48 },
      { "type": "Col", "children": [
        { "type": "Text", "value": "Black Sugar Hoick Latte", "size": "md", "weight": "semibold", "color": "emphasis" },
        { "type": "Text", "value": "16oz Iced · Boba · $6.50", "size": "sm", "color": "secondary" } ] } ] },
    { "type": "Row", "key": "Classic Milk Tea", "align": "center", "children": [
      { "type": "Image", "src": "https://cdn.openai.com/API/storybook/milktea.png", "size": 48 },
      { "type": "Col", "children": [
        { "type": "Text", "value": "Classic Milk Tea", "size": "md", "weight": "semibold", "color": "emphasis" },
        { "type": "Text", "value": "16oz Iced · Boba · $5.50", "size": "sm", "color": "secondary" } ] } ] },
    { "type": "Row", "key": "Matcha Latte", "align": "center", "children": [
      { "type": "Image", "src": "https://cdn.openai.com/API/storybook/matcha.png", "size": 48 },
      { "type": "Col", "children": [
        { "type": "Text", "value": "Matcha Latte", "size": "md", "weight": "semibold", "color": "emphasis" },
        { "type": "Text", "value": "16oz Iced · Oat milk · $6.00", "size": "sm", "color": "secondary" } ] } ] } ] },
  { "type": "Divider", "flush": true },
  { "type": "Col", "children": [
    { "type": "Row", "children": [ { "type": "Text", "value": "Subtotal", "size": "sm" }, { "type": "Spacer" }, { "type": "Text", "value": "$19.75", "size": "sm" } ] },
    { "type": "Row", "children": [ { "type": "Text", "value": "Sales tax (8.75%)", "size": "sm" }, { "type": "Spacer" }, { "type": "Text", "value": "$1.72", "size": "sm" } ] },
    { "type": "Row", "children": [ { "type": "Text", "value": "Total with tax", "weight": "semibold", "size": "sm" }, { "type": "Spacer" }, { "type": "Text", "value": "$21.47", "weight": "semibold", "size": "sm" } ] } ] },
  { "type": "Divider", "flush": true },
  { "type": "Col", "children": [
    { "type": "Button", "label": "Purchase", "onClickAction": { "type": "purchase" }, "style": "primary", "block": true },
    { "type": "Button", "label": "Add to cart", "onClickAction": { "type": "add_to_cart" }, "style": "secondary", "block": true } ] }
]}
```

### purchase_complete: success confirmation (a post-order card)

```json
{ "type": "Card", "size": "lg", "children": [
  { "type": "Col", "gap": 3, "children": [
    { "type": "Row", "align": "center", "gap": 2, "children": [
      { "type": "Icon", "name": "check-circle-filled", "color": "success" },
      { "type": "Text", "size": "sm", "value": "Purchase complete", "color": "success" } ] },
    { "type": "Divider", "color": "subtle", "flush": true },
    { "type": "Row", "gap": 3, "children": [
      { "type": "Image", "src": "/blue-chair.png", "alt": "Blue folding chair", "size": 80, "frame": true },
      { "type": "Col", "gap": 1, "children": [
        { "type": "Title", "value": "Blue folding chair", "maxLines": 2 },
        { "type": "Text", "value": "Free delivery • 14-day returns", "size": "sm", "color": "secondary" } ] } ] } ] },
  { "type": "Col", "gap": 2, "padding": { "y": 2 }, "children": [
    { "type": "Row", "children": [ { "type": "Text", "value": "Estimated delivery", "size": "sm", "color": "secondary" }, { "type": "Spacer" }, { "type": "Text", "value": "Thursday, Oct 8", "size": "sm" } ] },
    { "type": "Row", "children": [ { "type": "Text", "value": "Sold by", "size": "sm", "color": "secondary" }, { "type": "Spacer" }, { "type": "Text", "value": "OpenAI", "size": "sm" } ] },
    { "type": "Row", "children": [ { "type": "Text", "value": "Paid", "size": "sm", "color": "secondary" }, { "type": "Spacer" }, { "type": "Text", "value": "$20.00", "size": "sm" } ] } ] },
  { "type": "Button", "label": "View details", "onClickAction": { "type": "order.view_details" }, "variant": "outline", "pill": true, "block": true }
]}
```

### software_purchase: Card `confirm`/`cancel` footer, Select, DatePicker and editable Text

```json
{ "type": "Card", "size": "lg", "padding": 0,
  "confirm": { "label": "Confirm", "action": { "type": "request.submit" } },
  "cancel":  { "label": "Discard", "action": { "type": "request.discard" } },
  "children": [
    { "type": "Row", "align": "center", "padding": { "x": 4, "top": 4, "bottom": 1 }, "children": [ { "type": "Title", "value": "Software purchase", "size": "sm" } ] },
    { "type": "Col", "padding": { "left": 4, "right": 2 }, "children": [
      { "type": "Row", "padding": { "right": 2 }, "children": [
        { "type": "Text", "value": "What is it for?", "size": "sm", "color": "secondary" }, { "type": "Spacer" },
        { "type": "Box", "padding": 1.1, "children": [
          { "type": "Text", "value": "ChatGPT Business", "textAlign": "end", "width": "200px",
            "editable": { "name": "purchase.purpose", "required": true, "placeholder": "Vendor or tool" } } ] } ] },
      { "type": "Row", "children": [
        { "type": "Text", "value": "Start date", "size": "sm", "color": "secondary" }, { "type": "Spacer" },
        { "type": "DatePicker", "name": "purchase.start", "defaultValue": "2025-10-01", "align": "end", "variant": "ghost" } ] },
      { "type": "Row", "children": [
        { "type": "Text", "value": "Volume", "size": "sm", "color": "secondary" }, { "type": "Spacer" },
        { "type": "Select", "name": "purchase.volume", "defaultValue": "5", "variant": "ghost",
          "options": [ { "label": "1 seat", "value": "1" }, { "label": "3 seats", "value": "3" }, { "label": "5 seats", "value": "5" }, { "label": "10 seats", "value": "10" }, { "label": "25 seats", "value": "25" } ] } ] },
      { "type": "Row", "children": [
        { "type": "Text", "value": "Frequency", "size": "sm", "color": "secondary" }, { "type": "Spacer" },
        { "type": "Select", "name": "purchase.frequency", "defaultValue": "monthly", "variant": "ghost",
          "options": [ { "label": "Monthly", "value": "monthly" }, { "label": "Quarterly", "value": "quarterly" }, { "label": "Yearly", "value": "yearly" } ] } ] } ] },
    { "type": "Row", "padding": { "y": 4, "left": 4, "right": 5 }, "background": "surface-elevated-secondary", "border": { "top": { "size": 1 } }, "children": [
      { "type": "Text", "value": "Total amount", "size": "sm" }, { "type": "Spacer" }, { "type": "Box" },
      { "type": "Text", "value": "$125 / month", "weight": "semibold", "size": "sm" } ] }
]}
```

Use this shape for a quantity picker (`Select` with options "1"…"10") if we want one in place of the +/− buttons.

### create_task: Form + submit button (how form state reaches the agent)

```json
{ "type": "Card", "size": "lg", "children": [
  { "type": "Form", "onSubmitAction": { "type": "task.create" }, "children": [
    { "type": "Col", "gap": 3, "children": [
      { "type": "Text", "value": "Design resizable popup mode", "size": "lg", "weight": "semibold",
        "editable": { "name": "task.title", "required": true, "placeholder": "Task title", "autoFocus": false, "autoSelect": false } },
      { "type": "Text", "value": "Create a design proposal for …", "minLines": 5,
        "editable": { "name": "task.body", "required": true, "placeholder": "Describe the task…" } },
      { "type": "Divider", "flush": true },
      { "type": "Row", "align": "center", "gap": 3, "children": [
        { "type": "Row", "align": "center", "gap": 2, "children": [
          { "type": "DatePicker", "name": "task.due", "placeholder": "Due date", "defaultValue": "2025-10-16", "clearable": true, "pill": true } ] },
        { "type": "Spacer" },
        { "type": "Button", "submit": true, "label": "Create task", "style": "primary" } ] } ] } ] }
]}
```

On submit, the action is sent as `{ type: "task.create", payload: { task: { title, body, due } } }` (dot paths nest).

### enable_notification: a two-button choice

```json
{ "type": "Card", "size": "lg", "children": [
  { "type": "Col", "align": "center", "gap": 4, "padding": 4, "children": [
    { "type": "Box", "background": "green-400", "radius": "full", "padding": 3, "children": [ { "type": "Icon", "name": "check", "size": "3xl", "color": "white" } ] },
    { "type": "Col", "align": "center", "gap": 1, "children": [
      { "type": "Title", "value": "Enable notification" },
      { "type": "Text", "value": "Notify me when this item ships", "color": "secondary" } ] } ] },
  { "type": "Row", "children": [
    { "type": "Button", "label": "Yes", "block": true, "onClickAction": { "type": "notification.settings", "payload": { "enable": true } } },
    { "type": "Button", "label": "No",  "block": true, "variant": "outline", "onClickAction": { "type": "notification.settings", "payload": { "enable": true } } } ] }
]}
```

Note that **"No" sends `enable: true`**. This bug is in OpenAI's own example. A well-formed payload can still carry a semantic error, so the agent should check actions against what was actually on screen and not trust the payload alone.

### chart_line_trend: line chart

```json
{ "type": "Card", "size": "lg", "children": [
  { "type": "Col", "gap": 6, "children": [
    { "type": "Row", "align": "center", "children": [
      { "type": "Text", "value": "Mobile sessions", "weight": "semibold", "size": "lg" }, { "type": "Spacer" },
      { "type": "Text", "value": "Last 10 days", "color": "tertiary", "size": "sm" } ] },
    { "type": "Chart", "showYAxis": true,
      "data": [ { "date": "2024-04-14", "mobile": 220 }, { "date": "2024-04-15", "mobile": 170 }, { "date": "2024-04-16", "mobile": 190 },
                { "date": "2024-04-17", "mobile": 360 }, { "date": "2024-04-18", "mobile": 410 }, { "date": "2024-04-19", "mobile": 180 },
                { "date": "2024-04-20", "mobile": 150 }, { "date": "2024-04-21", "mobile": 200 }, { "date": "2024-04-22", "mobile": 170 },
                { "date": "2024-04-23", "mobile": 230 } ],
      "series": [ { "type": "line", "dataKey": "mobile", "label": "Mobile" } ],
      "xAxis": { "dataKey": "date", "labels": { "2024-04-14": "Apr 14", "2024-04-15": "Apr 15", "…": "…", "2024-04-23": "Apr 23" } } } ] }
]}
```

### chart_stacked_bar: bar chart with a stack

```json
{ "type": "Chart", "barGap": 1, "showYAxis": true,
  "data": [ { "date": "2024-04-17", "desktop": 446, "android": 86, "ios": 360 },
            { "date": "2024-04-18", "desktop": 364, "android": 46, "ios": 410 },
            { "date": "2024-04-19", "desktop": 243, "android": 63, "ios": 180 } ],
  "series": [ { "type": "bar", "dataKey": "desktop", "label": "Desktop" },
              { "type": "bar", "dataKey": "android", "label": "Android", "stack": "mobile", "color": "red" },
              { "type": "bar", "dataKey": "ios", "label": "iOS", "stack": "mobile", "color": "red" } ],
  "xAxis": { "dataKey": "date", "labels": { "2024-04-17": "Apr 17", "2024-04-18": "Apr 18", "2024-04-19": "Apr 19" } } }
```

(The original has 7 days. The surrounding Card and header Row match the line chart.)

### chart_area_stacked: area chart

```json
{ "type": "Chart", "showYAxis": true,
  "data": [ { "month": "January", "desktop": 186, "mobile": 80 }, { "month": "February", "desktop": 305, "mobile": 200 },
            { "month": "March", "desktop": 237, "mobile": 120 }, { "month": "April", "desktop": 73, "mobile": 190 },
            { "month": "May", "desktop": 209, "mobile": 130 }, { "month": "June", "desktop": 214, "mobile": 140 } ],
  "series": [ { "type": "area", "dataKey": "desktop", "label": "Desktop", "color": "green", "stack": "traffic" },
              { "type": "area", "dataKey": "mobile",  "label": "Mobile",  "color": "green", "stack": "traffic" } ],
  "xAxis": { "dataKey": "month", "labels": { "January": "Jan", "February": "Feb", "March": "Mar", "April": "Apr", "May": "May", "June": "Jun" } } }
```

### ListView with a clickable row (from the Studio prompt's examples; template only)

```tsx
<ListView>
  {devices.map((item) => (
    <ListViewItem key={item.id} gap={3}
      onClickAction={{ type: "device.select", payload: { id: item.id } }}>
      <Box background="alpha-10" radius="sm" padding={2}><Icon name={item.icon} size="lg" /></Box>
      <Col gap={0}>
        <Text value={item.name} size="sm" weight="semibold" />
        <Caption value={`${item.status} • ${item.os} ${item.version}`} color="secondary" />
      </Col>
    </ListViewItem>
  ))}
</ListView>
```

### Table: no gallery example exists. This one is **built from the spec**, not scraped.

```json
{ "type": "Card", "size": "md", "children": [
  { "type": "Table", "children": [
    { "type": "Table.Row", "header": true, "children": [
      { "type": "Table.Cell", "children": [ { "type": "Text", "value": "Item", "size": "sm", "weight": "semibold" } ] },
      { "type": "Table.Cell", "align": "center", "children": [ { "type": "Text", "value": "Qty", "size": "sm", "weight": "semibold" } ] },
      { "type": "Table.Cell", "align": "end", "children": [ { "type": "Text", "value": "Price", "size": "sm", "weight": "semibold" } ] } ] },
    { "type": "Table.Row", "key": "shawarma", "children": [
      { "type": "Table.Cell", "children": [ { "type": "Text", "value": "Chicken Shawarma", "size": "sm" } ] },
      { "type": "Table.Cell", "align": "center", "children": [ { "type": "Text", "value": "1", "size": "sm" } ] },
      { "type": "Table.Cell", "align": "end", "children": [ { "type": "Text", "value": "$8.50", "size": "sm" } ] } ] }
  ]}
]}
```

---

## 6. Other gallery cards (patterns only)

| id | worth knowing |
|---|---|
| flight_tracker | `theme: "dark"` + `background: "linear-gradient(...)"`. A progress bar made from a nested `Box` (`width: "30%"`, `radius: "full"`) |
| weather_current / weather_forecast | gradient background, `textAlign: "center"`, Image `size` |
| player_card | `background: "url(https://…) no-repeat center / cover"`: **an external URL inside a CSS string** |
| playlist | `Image` with `flush` + `height` + `fit`, icon-only `Button` (`iconStart: "play"`, `uniform: true`), keyed rows |
| ride_status | `Col minWidth: "auto"`, `Text truncate`, round avatar (`radius: "full"`) |
| channel_message | `Markdown` with **bold** and numbered lists |
| create_event | Card confirm/cancel, keyed rows with dashed `border` |
| draft_email | editable Text fields, `minLines` |
| event_session / view_event | `Box` with `align`/`justify` centring an Icon, colour via hex, `align: "stretch"` |

---

## 7. What this means for the renderer

1. **Validate against chatkit-components.d.ts.** Check per-node `type` against the 30 known names, required props (`value`, `label`, `name`, `src`, `data/series/xAxis`) and enum values. If an enum value is wrong, drop the prop and keep the node, because the spec itself says invented props are "silently ignored".
2. **Unknown `type`:** render a placeholder for that node only and keep its siblings. Studio's runtime already has an undocumented `Grid.Item`, so new types will turn up.
3. **Where nodes may appear:** `ListViewItem` is only valid directly under `ListView`, `Table.Row` under `Table`, and `Table.Cell` under `Table.Row`. A text-bearing component never has `children`.
4. **Coercion:** numbers arrive as strings (`"label": "1"`, `"value": "28"`). Expect the reverse from the model too, e.g. `value: 8.5`. Coerce primitives to strings for text props.
5. **`key` is the identity for updates.** Match old and new trees on `key` (ListViewItem, Row) and on `name` (form controls) so local state survives a replacement: an open Select, typed input, a "show more" toggle.
6. **No raw CSS** in `background` or `color` (decided 30 Oct). Accept spec tokens only: surface, text, border, alpha and primitive colour names. The gallery passes `url(...)` and gradients, so models will too. Omit those with a warning (catalogue case M08).
7. **Charts:** `xAxis.labels` maps raw values to display text. Each `series.dataKey` must exist in the data rows, and numeric values must be finite. Charts don't mirror in RTL (§4c).
8. **Actions:** only dispatch `ActionConfig` objects with a string `type`. Honour `loadingBehavior` to block double sends.

---

## 8. Our restaurant widgets

> **The styling is optional.** The brief judges the payload↔UI contract and bad-input handling, not looks. These fixtures matter for what they exercise: keyed rows, dish `position`, a sold-out dish that can only decrease, a Card `confirm` that is absent when blocked, one child order for EN/AR, and allowlisted actions. The emoji tiles and meter are decoration. Drop either rather than widen the validator to accept it. **No raw CSS:** `background` takes spec tokens only, so the gradients were removed (decided 30 Oct; see M08 in [payload-test-cases.md](payload-test-cases.md)). The model-shaped bad inputs are M01–M14 there.

These are our own menu and confirmation widgets, designed from scratch. They borrow a few ideas from a mobile mock-up the user shared: dark cards, rounded icon tiles, a progress meter, and a clear action on every block. Everything is built from spec components only. Both widgets were rendered in ChatKit Studio in every state, and the compiled trees are saved as Studio reference fixtures. They are not valid fixtures for the current renderer: Box nodes and action properties are not supported yet.

| | Template, schema and states (importable into Studio) | Compiled fixtures (`fixtures/studio/`) | Studio renders (`output/widget-review/`) |
|---|---|---|---|
| Menu | [restaurant-menu.widget.json](widgets/restaurant-menu.widget.json) | `restaurant-menu-en`, `-ar`, `-ready-en` | `restaurant-menu-en.png`, `restaurant-menu-ar-rtl.png` |
| Confirm | [restaurant-confirm.widget.json](widgets/restaurant-confirm.widget.json) | `restaurant-confirm-en`, `-ar`, `-blocked-en` | `restaurant-confirm-en.png`, `-blocked-en.png`, `-ar-rtl.png` |

All the screenshots still show the old gradient backgrounds, which have since been replaced with tokens. The confirm screenshots were also taken before two SPEC wording fixes, which the fixtures already include: "You removed it" in place of "was removed", and "Total without sold-out items" in the blocked state.

### Menu: `ListView theme="dark"` (SPEC requires a ListView root for the menu)

```
┌ header item ─────────────────────────────────────────┐
│ [🍽️]  Order food                         (EN)(عربي)  │  Box, surface-elevated-secondary, radius xl
│       Open now · 25–35 min                           │
└──────────────────────────────────────────────────────┘
 [🌯]  Chicken Shawarma          (−)  1  (+)             dish item, position 1
       $8.50
 [🥗]  Tabbouleh                 (−)  1  (+ disabled)    sold out: dim name, badge, can only go down
       $5.50  [Sold out]
┌ footer item ─────────────────────────────────────────┐
│ Your order                                   4 items │
│ Free delivery at $30.00            $28.00 / $30.00   │
│ ████████████████████████████░░  (93%)                │  progress meter
│ Subtotal                                    $28.00   │
│ ⓘ Remove sold-out items to check out                 │  only when blocked
│ [            Checkout (disabled)            ]        │
└──────────────────────────────────────────────────────┘
```

- **Emoji tiles, not photos.** Each dish has an `emoji` field, shown as a `Title` inside `Box size={48} radius="lg" background="alpha-10"`. This needs no image assets, and SPEC doesn't allow unrestricted image URLs. Switch to `Image` once the backend serves allowlisted dish photos.
- **The stepper** is two `uniform` Buttons around a `Box minWidth={24}`, so the row doesn't jump as the count changes. `−` is disabled at 0 and `+` is disabled when the dish is sold out.
- **The meter** is a track `Box` with a fill `Box width={percent}`. The backend computes `delivery_percent` and every display string from minor units. Templates never do maths, and nothing parses a display string.
- **Header and footer items carry no `position`** (SPEC: positions count dish rows only). `limit={items.length + 2}` stops "Show more" from hiding the footer.

### Confirm: `Card theme="dark"` with the Card's own `confirm`/`cancel`

- **Footer buttons:** "Place order" is `confirm` and fires `order.confirm {order_id}`. "Edit order" is `cancel` and fires `order.edit {order_id}`. Using the Card's built-in footer keeps the buttons consistent and in place.
- **Blocked state** (a sold-out line is still in the order): the template passes `confirm={blocked ? undefined : {...}}`. The compiled tree then **has no confirm key at all**, so only "Edit order" shows; the Card has no `disabled` option to use instead. The sold-out line stays visible with a dimmed name and a `Sold out` badge. The total is labelled "Total without sold-out items" (SPEC: never present an interim total as the payable total).
- **Notice row:** `Row background="alpha-10" radius="lg"` with an `info` icon. It renders only when `notice` is set.

### Interaction contract (matches SPEC allowlist)

| Control | Action | Payload | Pending behaviour |
|---|---|---|---|
| `+` / `−` | `cart.add` / `cart.remove` | `{id, position}` | `self`: only that button disables |
| EN / عربي | `locale.set` | `{lang}` | `container` |
| Checkout | `checkout.start` | `{}` | `container`. Disabled while `cart.blocked` |
| Place order | `order.confirm` | `{order_id}` | `container`. Absent while `blocked` |
| Edit order | `order.edit` | `{order_id}` | `container` |

The payloads carry no `version`. Per SPEC, the action envelope carries `widget_id`, `revision` and `action_id`. Rows and lines are keyed by dish `id`, so a sell-out or language switch updates them in place without remounting.

### What Studio showed us (and what it couldn't)

- **The host must be dark.** `ListView theme="dark"` sets dark *text* tokens but has no background prop. On Studio's light canvas the dish rows rendered invisible (white on white). The current renderer does not implement this theme; a dark host surface remains a planned requirement.
- **RTL mirrors correctly** once `dir="rtl"` is set on the widget root: tiles, steppers, footer buttons and the meter all flip. This illustrates the planned "renderer owns mirroring" approach with one child order; it does not verify our renderer. (Studio needed a re-render after the attribute was added, so test mirroring on a fresh render.)
- **Number-only strings flip inside RTL.** Studio showed `$28.00 / $30.00` as `$30.00 / $28.00`, and `1 × $8.50` as `$8.50 × 1`. A proposed fix is to wrap every text value in `<bdi>` (`dir=auto`); the current renderer does not do this. A string with no letters then resolves to LTR, and Arabic sentences stay RTL. The payload doesn't need to change. **We haven't verified this in our renderer yet.**
- **Language buttons stay `[EN, عربي]` in one order;** the active one is `solid`. Under RTL they show in mirrored order, which is correct.

### Not done (on purpose)

- **Dish photos:** no assets, and URLs are restricted (see above).
- **A post-order status card** (e.g. an ETA meter after "Place order"): not in the brief. The same meter pattern would work if we add one.
- **Whole-row tap to add a dish:** possible with `ListViewItem.onClickAction`, but it would compete with the stepper buttons.

### Studio tip

To preview a widget, write a `.widget.json` (`{id, name, view, defaultState, states: [{id, name, value}], schema, jsonSchema: {}, schemaMode: "zod"}`) and open `https://widgets.chatkit.studio/import#<base64url(UTF-8 JSON), no padding>`. Each entry in `states` becomes a tab. The preview stays blank until `schema` is a valid zod module. Turn on Studio's dark preview (the moon icon) for `theme="dark"` widgets.
