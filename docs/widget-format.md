# ChatKit widget format — what you need to know

Your renderer takes a **ChatKit widget payload** (JSON) and renders it. This note is a summary; the authoritative spec is OpenAI's ChatKit widget documentation:

- Widgets guide: https://developers.openai.com/api/docs/guides/chatkit-widgets
- Component reference (all components + props): https://widgets.chatkit.studio
- Python SDK concepts: https://openai.github.io/chatkit-python/concepts/widgets

## Shape

Every payload has a **root** that is one of a small set of container types, most commonly:

- **Card** — a single bordered container for one piece of content (a summary, a confirmation, a form).
- **ListView** — a scrollable list of items (options, files, results).

Inside the root is a tree of **components**: text, images, badges, buttons, rows/columns for layout, plus data components like **tables** and **charts**. Each component is an object with a `type` and its own props.

## Bad payloads

The `payloads/` folder has a few **valid** examples so you can see the format. Real model output won't always look like them — it comes from a language model, so it can be malformed in all sorts of ways. Part of the task is working out how a payload can be broken and handling it: a good renderer validates the payload, renders what it safely can, and shows a clear fallback for the rest — never a blank screen or an uncaught error that takes down the page.

## Core types to support

At minimum: **Card**, **ListView**, a **text** component, a **table**, and a **chart** (bar or line is enough). Anything beyond that is a bonus; unknown types must degrade gracefully.
