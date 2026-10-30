# ChatKit widget payload test cases

Last checked: 30 October 2026. This is a test catalogue for the assessment renderer, not a claim that the full widget is implemented or that the cases have passed in a browser.

## Scope and sources

Test the **compiled JSON component tree** pasted into the playground, not a Studio `.widget` authoring template containing `view` and state/schema. The brief requires Card, ListView, text, table and a bar or line chart, graceful handling of unknown types, and useful output even when model-generated input is broken. The [ChatKit widget guide](https://developers.openai.com/api/docs/guides/chatkit-widgets) describes components and their props; the [Python SDK widget reference](https://openai.github.io/chatkit-python/api/chatkit/widgets/) and [JavaScript WidgetsOption reference](https://openai.github.io/chatkit-js/api/openai/chatkit/type-aliases/widgetsoption/) also identify `Basic` as a root. `Basic` is outside the stated minimum, not inherently invalid ChatKit. Consult the [actions guide](https://developers.openai.com/api/docs/guides/chatkit-actions) and [SDK action concepts](https://openai.github.io/chatkit-python/concepts/actions/) for action routing and validation. [Studio](https://widgets.chatkit.studio/) provides a component reference and authoring tool; local `chatkit-components.d.ts` captures a reference snapshot. Documentation may evolve; check the version used for the submission.

The current playground supports only a Card with direct Text children. Its validator was called directly for cases B01–B09, C01, C03 and S01 below; recorded results are actual backend return values, **not observed browser renderings**. Visible outcomes below are expectations from the project failure policy and frontend code, pending browser verification. Other cases are proposed and unexecuted. `valid`, `partial`, `invalid`, issue codes and limits are this project's contract, not promises made by ChatKit.

## How to run and record

1. Start the backend and frontend using the project's configured environment. Open the playground. Paste each complete source into **Payload source** and select **Validate widget**. For a retained-preview scenario, first validate `{"type":"Card","children":[{"type":"Text","value":"Previous"}]}`.
2. Record date, commit, browser, input ID, status, diagnostics and path, visible result, interactions, console errors, and pass/fail. Capture screenshots for visual problems. For API cases send `POST /api/payloads/validate` with `Content-Type: application/json` and body `{"source":"<escaped widget source>"}`; malformed widget JSON belongs inside the string, not in a malformed request body.
3. Check both the specific expected result and the shared invariant: no blank application, uncaught error, payload code execution, or unintended order mutation. A previous preview retained after failure must be identified as potentially outdated.
4. When implementing missing behavior, turn the relevant case into a focused failing integration or browser test first, implement the smallest fix, rerun it, then run the existing full suite. A catalogue alone is not an automated test or an observed RED/GREEN cycle.

## Baseline and broken payloads

Each JSON block is the entire widget source, except the intentionally malformed B01. The current results are direct `validate_source` observations; they do not establish HTTP, layout, or interaction behavior.

| ID | Source | Expected visible outcome / acceptance | Current validator observation |
|---|---|---|---|
| C01 | `{"type":"Card","children":[]}` | Empty Card with an explicit empty message; valid. | `valid`, empty card preview. |
| C02 | `{"type":"Card","children":[{"type":"Text","value":"Hello"}]}` | Card displays Hello, no diagnostics. | Not separately executed; baseline expected. |
| C03 | `{"type":"ListView","children":[]}` | Valid list root; empty list presented safely. | `invalid`, `invalid_root`; valid ChatKit root not yet supported. |
| B01 | `{"type":"Card","children":[` | Reject malformed source, report problem; retain prior preview as outdated if one exists. | `invalid`, `invalid_json`, null preview. |
| B02 | `[]` | Reject non-object root; report root error. | `invalid`, `invalid_root`, null preview. |
| B03 | `{"type":"Card"}` | Reject root without required children. | `invalid`, `invalid_root`, null preview. |
| B04 | `{"type":"Card","children":[{"type":"Text","value":"Before"},{"type":"Mystery"},{"type":"Text","value":"After"}]}` | Show Before, a placeholder in the middle, and After; diagnostic identifies child 1. | `partial`, `unsupported_child` at `$.children[1]`; preview has text, problem, text. |
| B05 | `{"type":"Card","children":[{"type":"Text"}]}` | Missing required value: local placeholder and diagnostic. | `partial`, `unsupported_child` at `$.children[0]`; problem preview. |
| B06 | `{"type":"Card","children":[{"type":"Text","value":42}]}` | Wrong value type: local placeholder, no implicit conversion. | `partial`, `unsupported_child` at `$.children[0]`; problem preview. |
| B07 | `{"type":"Card","type":"Card","children":[]}` | Reject duplicate JSON object keys, even when values match. | `invalid`, `invalid_json`, null preview. |
| B08 | `{"type":"Card","children":[{"type":"Text","key":"a","value":"First"},{"type":"Text","key":"a","value":"Second"}]}` | First text remains; second gets noninteractive placeholder and duplicate-key diagnostic. | `partial`, `duplicate_key` at `$.children[1]`; text then problem. |
| B09 | `{"type":"Card","children":[{"type":"Text","value":"Hello","onClick":"alert(1)"}]}` | Show Hello; omit executable property and warn; no execution. | `partial`, `unsupported_property` at `$.children[0].onClick`; text preview. |
| S01 | `{"type":"Card","children":[{"type":"Text","value":"<script>alert(1)</script>"}]}` | Show literal text, never execute it. | `valid`, text preserved in preview; browser execution behavior not tested. |

Additional copyable cases, all **not executed**:

| ID | Payload or preparation | Expected result |
|---|---|---|
| B10 | `{"type":"Card","children":{}}` | Invalid root; no candidate preview. |
| B11 | `{"type":"Card","children":[null,17,"text"]}` | Partial; three position-preserving placeholders with paths, no crash. |
| B12 | `{"type":"Card","children":[{"type":"Text","value":"OK","key":42}]}` | Text remains, warning at child key; no unsafe identity reuse. |
| B13 | `{"view":"<Card />","state":{}}` | `unsupported_template_format`; explain compiled tree is required; never execute template. |
| B14 | `{"type":"Card","children":[{"type":"Text","value":NaN}]}` | Reject nonstandard JSON constant; no silent repair. |
| B15 | `{"type":"Card","children":[{"type":"Text","value":"\ud800"}]}` (six literal escape characters in source) | HTTP 422 `invalid_unicode`, safe notice and no server error. Also test a literal unpaired surrogate sent through a client capable of producing it. |
| B16 | `{"type":"Basic","children":[]}` | Valid SDK root but outside current required subset: explicit unsupported-root behavior, no crash; do not describe as universally invalid. |
| B17 | `{"type":"Card","children":[{"type":"Text","value":"A","weight":"semibold"}]}` | Once display props are supported, valid text renders with semibold weight without warning. Currently the property is outside the implemented subset. |

## Components and interactions to implement and verify

These are acceptance targets for the planned renderer; they are not current observations. Use the exact component and prop schema of the selected ChatKit version; adapt any fixtures from `widget-examples.md` rather than passing Studio authoring templates directly.

| ID | Scenario / input | Expected result |
|---|---|---|
| F01 | Compiled menu EN and AR, and confirmation EN and AR from the four supplied templates. | Names, prices, availability and controls match fixture data; Arabic and mixed-direction text are legible; language switch does not lose order state. Mark conversion provenance and adaptations. |
| F02 | ListView with several ListViewItem children and a documented `limit`. | Items render in order; verify limit/show-more behavior where supported, including empty list and long list. |
| F03 | Card containing nested Row/Col and Text, including empty Text and long unbroken Unicode text. | Layout follows supported props, text is intact, and content stays usable on narrow viewports. |
| F04 | Valid Table with headers, multiple rows and empty cells, using the selected component reference. | Headers align with the correct cells, values remain readable; overflow is usable on a narrow screen. |
| F05 | Table with malformed rows/cells or an invalid required value surrounded by valid siblings. | Affected subtree gets a visible diagnostic/placeholder; other siblings remain; no fabricated cells. |
| F06 | Valid bar chart and line chart, each with `data`, `series` and `xAxis` according to reference. | Correct labels and data/series mapping, legible values, no crash for zero and negative numbers. Verify a textual accessible representation. |
| F07 | Chart missing `data`, with non-array `series`, or a series referring to a missing data key. | Diagnose invalid configuration and show a placeholder; never invent data. |
| F08 | Form with named Input and Select, valid submit action, including a dotted field name. | Required inputs collect intended values; submitted action reflects the documented nested name behavior; no order mutation from playground. |
| F09 | Missing required form name, invalid select option, or invalid quantity. | Retain entered draft, show field error, prevent submission. Check again on server. |
| F10 | Button with documented action object; repeat with unknown action type, wrong payload type and forged order/version. | Supported live action reaches authorized handler with correct payload; unsupported/forged actions cannot mutate state. Playground actions remain inert. |
| F11 | Disabled button, and a pending action using `loadingBehavior` where supported. | Disabled/pending control cannot be activated; verify duplicate clicks cannot create duplicate order effects. |
| F12 | Unknown child nested between known children; unknown property on a known node. | Local placeholder for unknown node; omit and diagnose unknown prop; preserve valid siblings. |
| F13 | Model-proposed price conflicts with authoritative backend; repeat with missing backend price. | Backend price wins with warning; if unavailable, affected dish is disabled and visible as a placeholder. |
| F14 | English and Arabic with punctuation, prices and mixed text; switch locale twice. | Content remains legible; layout mirrors once; charts retain intended direction; draft and order state persist. |
| F15 | Card status/confirm/cancel and controls with keyboard and screen reader. | Supported labels, focus, semantics and action state are usable; unsupported properties get a truthful diagnostic. |

## Limits, transport and recovery

The following bounds are project targets, not ChatKit-wide limits. Generate boundary inputs programmatically and paste/send them; JSON source size is measured in UTF-8 bytes, not characters. Check exact boundary and one above, while keeping other limits below their thresholds.

| ID | Test | Expected result |
|---|---|---|
| L01 | Source 32,768 vs 32,769 UTF-8 bytes, including a multibyte variant. | At limit processed; over limit rejected safely. Browser and backend enforce consistently. |
| L02 | Root Card with 100 vs 101 direct children; text length 4,096 vs 4,097 Unicode characters; key length 128 vs 129. | Boundary accepted if otherwise valid; over limit rejects entire candidate and retains old preview marked outdated. |
| L03 | JSON container depth 16 vs 17; 4,096 vs 4,097 JSON containers; separately 1,000 vs 1,001 rendered nodes within all other limits. Include brackets inside escaped strings. | Enforce applicable limits without treating quoted brackets as structure. Where limits conflict, document which is reached first. |
| L04 | Tables 100/101 rows and 20/21 columns; charts 200/201 points and 4/5 series; quantity 0, 99, -1, 100 and non-integer. | At-limit valid data accepted; over-limit data rejected; invalid quantity produces field error and blocks submission. |
| L05 | More than 100 independent diagnostics. | At most 100 issues; final issue indicates omitted diagnostics. |
| A01 | Wrong content type; malformed envelope; missing/extra `source`; non-string `source`; duplicate envelope keys. | HTTP 415 for content type; HTTP 422 for malformed envelope; no raw request or stack trace in response. |
| A02 | HTTP request body exactly 262,144 bytes and 262,145 bytes, with source otherwise small enough where possible. | At limit proceeds to envelope validation; over limit returns HTTP 413. Distinguish body limit from source limit. |
| R01 | Submit a valid preview, then B01, then a corrected valid payload. Repeat B01 on a fresh page. | Existing view persists with outdated notice; initial failure shows explicit error; corrected submission replaces it and clears stale notice. |
| R02 | Submit valid input, then simulate offline API or malformed response; retry after recovery. | Preserve source and previous preview, show error, never report success, allow retry. |
| R03 | Submit two payloads with controlled out-of-order responses. | Only latest submission can update preview and diagnostics; no old response overwrites it. |
| R04 | Live flow: draft an input, receive an invalid update, then resync; deliver duplicate and stale revisions. | Keep draft and last valid view, pause unsafe actions, report stale state; resync restores fresh state; duplicate/stale updates cannot overwrite newer state. Requires live implementation. |
| S02 | Nested executable-looking props, unsafe URL/action, script-like text and oversized nested structures. | Never execute input, fetch arbitrary URLs or dispatch unsafe actions; show safe diagnostics. Verify in a controlled browser environment. |
| S03 | Cross-session order action, stale or forged action, repeated/concurrent confirmation. | Backend denies unauthorized/stale requests and prevents duplicate effects; public errors contain no secrets. Requires live backend. |

## Execution record

On 30 October 2026, the backend's `validate_source` function was invoked directly for C01, C03, B01–B09 and S01, using the inputs shown. The values in the table are the returned status, issue code/path and preview structure. C02 and all subsequent coverage are unexecuted. No API request, browser rendering, console, action, accessibility, or full-suite result is implied by these observations.
