# ChatKit Studio reference fixtures

Data-only ChatKit Studio trees. These are reference designs, not valid fixtures for the current renderer: validation returns partial because Box nodes and action properties are not supported. They do not demonstrate working application interactions. Each was compiled by ChatKit Studio from a template in `docs/widgets/` and captured from the live preview on 2026-10-30. Design notes are in `docs/widget-examples.md` §8.

| Fixture | Source template / state | Policy adaptations |
|---|---|---|
| `restaurant-menu-en.json` | `restaurant-menu.widget.json` / Default | Sold-out dish keeps its qty; `+` disabled; checkout disabled with notice |
| `restaurant-menu-ar.json` | same / Arabic | Same child order as EN; Studio preview mirrors via `dir="rtl"`; application support is unverified |
| `restaurant-menu-ready-en.json` | same / Ready to check out | Sold-out dish at qty 0, checkout enabled |
| `restaurant-confirm-en.json` | `restaurant-confirm.widget.json` / Default | Notice says the customer removed the item (no silent removal) |
| `restaurant-confirm-ar.json` | same / Arabic | As EN |
| `restaurant-confirm-blocked-en.json` | same / Sold out in order | No `confirm` key; total labelled "Total without sold-out items" |

Payloads carry `{id, position}` or `{order_id}` only. `widget_id`, `revision` and `action_id` belong to the action envelope (SPEC.md, Actions and deduplication).
