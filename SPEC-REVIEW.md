# SPEC.md adversarial review: handoff for Codex

Method: a fresh-context reviewer read only SPEC.md and the contract (brief.docx, widget-format.md, widget-example/*), then I checked each finding against the spec text. Codex is the cross-model second pass. Line numbers point into SPEC.md.

Constraint the spec never states: **the brief's deadline is 5:00 PM today.** Every finding below should be judged against that.

## Blockers: fix before writing any code

1. **Scope doesn't fit the deadline (L3, L198–202, L328–354).** The brief expects the full product today: chat, Card/ListView/Table/Chart, live updates, interaction, EN/AR, the OpenRouter hookup, README, broken payloads, a failure-policy note, a PPT of up to 10 slides, transcripts and a zip. Slice 1 as written is only a Card+Text playground, and it carries strict mypy, Biome, Playwright, lockfile audits and one-MCQ-at-a-time review on top. Fix: make slice 1 a thin end-to-end ordering flow, give every slice a time cap, and cut the tooling ceremony down to typecheck plus a few integration/e2e checks.
2. **Hand-in deliverables are missing.** The spec has no plan for the PPT (≤10 slides), the AI transcripts, the `<id>_challenge-3.zip` name, the standalone failure-policy note, or the list of broken payloads with how each one renders. Fix: add a "Hand-in" section.
3. **Secret leak risk (L9).** `aiatcore/docs/brief.docx` contains the OpenRouter key, `.env` sits at the root, there's no `.gitignore`, and the folder isn't a git repo even though L338 says "commit". Fix: `git init`, add `.gitignore` covering `.env`, `docs/brief.docx` and `output/`, add `.env.example`, and build the zip from `git archive`. Note that the backend env var is named `OPEN_ROUTE_API_KEY`.
4. **The supplied examples are ignored, and their format is different (L16).** `widget-example/` does exist. Its files are **ChatKit Studio templates**: a JSX `view` string plus `defaultState`, a zod `schema` and `jsonSchema`. They are not `{type, children}` JSON trees. Fix: decide what the renderer accepts. Options are (a) a compiled JSON component tree only, (b) template plus state, or (c) both. Record the decision.
5. **Templates conflict with "never execute payload code" (L175).** The `view` strings contain JS expressions (`items.map(...)`, `lang === "ar" &&`). Fix: either reject templates explicitly and convert the examples to JSON trees as fixtures, or expand them server-side with a small whitelisted evaluator. Pick one. Option (a) with converted fixtures is the cheaper path.
6. **Who authors widgets: the model or the backend? (L45, L49–53)** The spec says translations are prepared in advance and the backend owns prices and availability. If so, the menu and confirm widgets are effectively backend templates and the model only picks intents, yet the brief says the agent replies with payloads. Fix: state the split explicitly. A reasonable one: the model emits text plus intents/tool calls, the backend builds the widget payload from menu state, and model-authored widgets go through the same validator.

## Major: contract gaps

7. **Slice 1 can't render any real payload (L215–218).** Card is root-only and Text must be a direct Card child, but the examples nest Text in Row/Col and use ListView, ListViewItem, Title, Caption, Badge, Button, Spacer and Divider. Fix: allow nesting and add Row, Col, Title, Caption, Badge, Button and ListView/ListViewItem.
8. **A real payload is never `valid` (L218, L228).** Common display props (`size`, `weight`, `color`, `textAlign`, `gap`) all trigger warnings. Fix: allowlist them, or treat them as known-and-ignored without a warning.
9. **No model contract.** The spec doesn't specify the OpenRouter call, which model, the system prompt that teaches the format, how text is told apart from widgets, or a message envelope. Fix: define `{kind: text|widget|widget_update, widget_id, revision, payload}` and the prompt.
10. **The agent never receives what the user saw (L25–29).** The snapshot is stored on the backend only. Fix: inject the rendered snapshot (row positions, ids, sold-out flags, quantities) into every model turn.
11. **Core protocol is left in "Remaining questions" (L356–365).** Widget identity, update targeting, revision ordering and action bodies are still undecided, and they're central to the brief. Fix: settle them now with `widget_id` plus a monotonic `revision`, apply an update only when it has a higher revision, and send actions as `{widget_id, revision, action_id, type, payload}`. The examples already carry `version` and `position: i+1`.
12. **Double-tap protection covers confirmation only (L61–65).** The brief applies it to every control. `cart.add`, `cart.remove` and `locale.set` can double-fire. Fix: give every action a client `action_id`, deduplicate it on the server, and disable the control while the request is in flight.
13. **Selects and forms are undefined (L69).** Fix: name Button, Select, Form and the quantity input, with their props and validation rules.
14. **The sold-out policy contradicts the example (L21–23).** `confirm-en` auto-removes Tabbouleh and shows a notice. The spec keeps the item and blocks confirmation. Fix: keep the spec's policy, which is defensible, but change the fixtures to match and justify the choice in the failure-policy note.
15. **"Malformed price" is undefined (L31–35).** Prices are display strings like `"$8.50"`. Fix: render backend prices only, and treat a model price that differs as a warning.
16. **The language-switch rule contradicts itself (L51).** "Messages stay in their sent language" conflicts with switching the order language, because the order lives inside an old menu widget message. Fix: the active ordering widget re-renders in the new locale, and only past text messages stay as sent.
17. **"The second one" is ambiguous (L27).** It's unclear which menu it refers to when several are in history, whether the header ListViewItem counts, and whether sold-out or placeholder rows count. Fix: resolve against the latest active menu, count dish rows only (sold-out included), and use the payload's `position`.
18. **Who owns RTL mirroring is unspecified (L55–57).** The example templates reverse child order by hand under `lang === "ar"`, so adding `dir="rtl"` flips those rows twice. Fix: the renderer owns mirroring through `dir` and logical CSS, and payloads must not reverse order by hand.
19. **Only one of three references was checked (L17).** Look up Table and Chart in widgets.chatkit.studio and in the chatkit-python widgets docs before calling them extensions.
20. **Inventory scope and the sell-out trigger aren't chosen (L158–160).** Fix: inventory is global and broadcast to all sessions, and an explicit trigger is picked (an admin button or a timer). A second tab shares the same cookie session.
21. **Persistence and auth are over-built (L93–97, L158–190).** SQLite durability across restarts, CSRF and per-resource ownership go beyond "keep the backend simple". Fix: in-memory state behind one lock, with restart durability documented as out of scope. Keep server-side validation and idempotency.

## Minor

22. **Style rules contradict the design (L307).** "No default parameters" and "no global state" clash with the inventory store, the SSE registry, Pydantic `X | None = None`, and React optional props. Add explicit exceptions. Note that AGENTS.md is at `~/.codex/AGENTS.md`.
23. **Lone surrogates.** A `source` string containing `\ud800` makes `.encode("utf-8")` raise during the size check, which surfaces as a 500. Map it to a 4xx code instead. Duplicate sibling `key`s break React identity across updates, so report them as an issue.
24. **Outcomes left undefined.** The spec doesn't give the `status` for an empty Card (it should be `valid` plus an empty-state message). Repeated invalid updates also have no way out: confirmation stays paused until an "authoritative sync" whose source is never named. Add a resync action.
25. **Environment pins are wrong or fragile (L274).** The spec pins Python 3.13.4, but the machine has 3.13.5. TypeScript 7.0.2 (the native-compiler line) is unverified. Use version ranges and document the minimum toolchain in the README.
26. **The streaming bonus conflicts with "never repair JSON" (L83, L243).** Either carve out a provisional tolerant prefix parser for streaming or drop the bonus explicitly.

## What the spec gets right (keep)

Backend-authoritative confirmation, validated actions instead of trusting model-supplied ones, selection state keyed by stable item ID, keeping the last valid widget when an update fails, a render plan with no raw property passthrough, and ignoring superseded responses.
