# Shared UI inventory

The console UI primitives live in `shared/ui` and consume the semantic tokens in `app/styles.css`. They intentionally have no runtime dependency beyond React and the browser's native controls.

| Primitive | Use | Accessibility contract |
| --- | --- | --- |
| `Button`, `IconButton` | actions and icon-only actions | native button keyboard behavior; `IconButton` requires an accessible label |
| `Select`, `TextField`, `TextArea` | editable form values | native label association, invalid/error and hint slots |
| `Checkbox`, `Radio` | boolean and mutually exclusive choices | native input remains keyboard accessible; custom visuals are decorative |
| `Slider`, `NumberValue` | continuous input and numeric display | range semantics from native input; numeric values use tabular figures and interaction blue |
| `SegmentedControl` | compact mutually exclusive choices | `radiogroup`/`radio` semantics, roving tab stop, arrow/Home/End keyboard navigation, and disabled options |
| `Tabs` | peer views | tablist/tab/tabpanel roles and selected panel linkage |
| `Card`, `Badge`, `Banner`, `EmptyState`, `LoadingIndicator` | layout and status feedback | status/alert roles only where appropriate; decorative marks are hidden |

## Mapping guidance

- Editable numbers use `TextField type="number"` and `NumberValue editable`; telemetry/read-only values use `NumberValue` with the `telemetry` tone on their surrounding status surface.
- `Select` keeps a native select for keyboard and form semantics, while the shared skin removes platform chrome and supplies one tokenized chevron with interaction, focus, disabled, and dark-theme states.
- Use `interaction` (blue) for operator input and primary navigation, `telemetry` for values returned by hardware, and `success`/`warn`/`danger`/`muted` for state communication.
- Keep native semantics. A visual segmented control must still expose `radiogroup` and `radio`; a status banner must not be used for arbitrary layout copy.
- `Button` is for actions. Do not use an anchor or a styled `div` as an interactive control.

Settings is the first migrated consumer. Other features can move control-by-control while retaining their existing business handlers and i18n keys.
