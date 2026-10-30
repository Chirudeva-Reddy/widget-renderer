# ChatKit Studio reference fixtures

Data-only ChatKit Studio trees supported by the runtime validator and renderer. Each fixture validates without diagnostics. Bounded Studio dimensions, padding, color tokens, icons, button presentation, list limits and Card confirm/cancel controls are rendered through data-only normalization. Pasted fixtures are previews: their buttons remain disabled and never acquire session or order authority. Live menu and confirmation builders still use authoritative application state.

Each was compiled by ChatKit Studio from a template in `docs/widgets/` and captured from its preview on 2026-10-30. The original fixture data and supplied source templates are preserved. Design notes are in `docs/widget-examples.md` §8.

| Fixture | Source template / state | Policy adaptations |
|---|---|---|
| `restaurant-menu-en.json` | `restaurant-menu.widget.json` / Default | Sold-out dish keeps its qty; `+` disabled; checkout disabled with notice |
| `restaurant-menu-ar.json` | same / Arabic | Same child order as EN; inherits `dir="rtl"` from the viewer locale |
| `restaurant-menu-ready-en.json` | same / Ready to check out | Sold-out dish at qty 0, checkout enabled |
| `restaurant-confirm-en.json` | `restaurant-confirm.widget.json` / Default | Notice says the customer removed the item (no silent removal) |
| `restaurant-confirm-ar.json` | same / Arabic | As EN |
| `restaurant-confirm-blocked-en.json` | same / Sold out in order | No `confirm` key; total labelled "Total without sold-out items" |

Payloads carry `{id, position}` or `{order_id}` only. `widget_id`, `revision` and `action_id` belong to the action envelope (SPEC.md, Actions and deduplication).
