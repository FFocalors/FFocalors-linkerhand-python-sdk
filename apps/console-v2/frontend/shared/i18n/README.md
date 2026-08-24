# Shared i18n

The shared catalog is the translation foundation for the Console V2 shell and
its seven feature pages. It contains hand-written `zh` and `en` strings; no
runtime machine translation or network request is involved.

## Coverage

- `app.*`: shell navigation, groups, loading/error states, simulator notice,
  safety lock, operator labels, and accessibility labels.
- `common.*`: buttons, statuses, camera controls, units, and shared labels.
- `device.*`: connection, telemetry curve, digital twin, joint targets,
  quick/basic/number presets, speed/torque, and operation feedback.
- `grasp.*`: grasp flow, object presets, tactile feedback, load, and controls.
- `vision.*`: camera, hand output, calibration, recognition, recording, and
  playback.
- `rps.*`: camera/output, game settings, match state, personalized strategy,
  moves, outcomes, and action tests.
- `actions.*`: pose/action composition, the four basic and five number preset
  inventory, local poses, playback, and legacy recording compatibility.
- `diagnostics.*`: telemetry curve, structured logs, filters, safety monitor,
  connection self-check, and raw data.
- `settings.*`: device connection, camera permissions, appearance/theme,
  locale, offline resources, advanced settings, reset, and draft feedback.

## Wiring a page

The app shell wraps the feature tree in `I18nProvider`; feature components
should use `useI18n()` so an English/Chinese selection re-renders every page:

```tsx
const { t, locale, setLocale } = useI18n();
```

Use a stable key at the render site:

```ts
import { createTranslator } from '../../shared/i18n';

const { t } = createTranslator();
// `createTranslator()` reads linkerhand-console-v2-locale, defaults to zh,
// and falls back to the Chinese catalog if an English key is absent.
const title = t('device.title');
const attempts = t('device.connection.attempt', { count: attempt });
```

The settings seam can own persistence and notify the app shell:

```ts
const localeStore = createLocaleStore();
localeStore.setLocale('en-US'); // normalizes and persists `en`
const translator = localeStore.translator();
```

`CatalogKey` is exported for typed key registries. Interpolation uses
`{{name}}` placeholders and leaves a placeholder intact when a value is not
provided. Unknown keys are returned as the key itself, making missing wiring
visible during development.
