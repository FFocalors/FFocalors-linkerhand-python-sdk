import { catalogs, enCatalog, zhCatalog, type CatalogKey } from './catalog';
import { createContext, createElement, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

export { catalogs, enCatalog, zhCatalog } from './catalog';
export type { CatalogKey } from './catalog';

export type Locale = 'zh' | 'en';
export type LocaleInput = string | null | undefined;
export const DEFAULT_LOCALE: Locale = 'zh';
export const FALLBACK_LOCALE: Locale = 'zh';
export const LOCALE_STORAGE_KEY = 'linkerhand-console-v2-locale';

export interface LocaleStorage {
  getItem(key: string): string | null;
  setItem?(key: string, value: string): void;
}

export type InterpolationValue = string | number | boolean | bigint | null | undefined;
export type InterpolationParams = Record<string, InterpolationValue>;

type PlaceholderNames<S extends string> = S extends `${string}{{${infer Name}}}${infer Rest}`
  ? Name extends `${infer Trimmed} ` ? PlaceholderNames<Rest> : Name | PlaceholderNames<Rest>
  : never;
type ParamsFor<K extends CatalogKey> = [PlaceholderNames<(typeof zhCatalog)[K]>] extends [never]
  ? InterpolationParams | undefined
  : InterpolationParams & Record<PlaceholderNames<(typeof zhCatalog)[K]>, InterpolationValue>;

export interface Translator {
  readonly locale: Locale;
  readonly fallbackLocale: Locale;
  t<K extends CatalogKey>(key: K, params?: ParamsFor<K>): string;
  has(key: CatalogKey): boolean;
}

export interface TranslatorOptions {
  /** Explicit locale; when omitted, the persisted locale is read. */
  locale?: LocaleInput;
  storage?: LocaleStorage | null;
  storageKey?: string;
  fallbackLocale?: Locale;
  catalogs?: Partial<Record<Locale, Partial<Record<CatalogKey, string>>>>;
}

/** Normalize browser/runtime locale values without guessing at unsupported languages. */
export function normalizeLocale(value: LocaleInput): Locale {
  const normalized = value?.trim().toLowerCase().replace('_', '-');
  if (normalized === 'en' || normalized?.startsWith('en-')) return 'en';
  if (normalized === 'zh' || normalized?.startsWith('zh-')) return 'zh';
  return DEFAULT_LOCALE;
}

function browserStorage(): LocaleStorage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}

export function readPersistedLocale(storage: LocaleStorage | null = browserStorage(), storageKey = LOCALE_STORAGE_KEY): Locale {
  try { return normalizeLocale(storage?.getItem(storageKey)); } catch { return DEFAULT_LOCALE; }
}

export function persistLocale(locale: LocaleInput, storage: LocaleStorage | null = browserStorage(), storageKey = LOCALE_STORAGE_KEY): Locale {
  const normalized = normalizeLocale(locale);
  try { storage?.setItem?.(storageKey, normalized); } catch { /* persistence is best effort */ }
  return normalized;
}

function interpolate(template: string, params?: InterpolationParams): string {
  if (!params) return template;
  return template.replace(/{{\s*([\w.-]+)\s*}}/g, (match, name: string) => {
    const value = params[name];
    return value === undefined || value === null ? match : String(value);
  });
}

export function createTranslator(localeOrOptions?: LocaleInput | TranslatorOptions, options?: TranslatorOptions): Translator {
  const opts = typeof localeOrOptions === 'object' && localeOrOptions !== null ? localeOrOptions : options ?? {};
  const locale = typeof localeOrOptions === 'object' && localeOrOptions !== null ? localeOrOptions.locale : localeOrOptions;
  const requested = locale === undefined ? readPersistedLocale(opts.storage, opts.storageKey) : normalizeLocale(locale);
  const fallbackLocale = opts.fallbackLocale ?? FALLBACK_LOCALE;
  const source = opts.catalogs ?? catalogs;
  const active = source[requested] ?? {};
  const fallback = source[fallbackLocale] ?? {};
  return {
    locale: requested,
    fallbackLocale,
    t(key, params) {
      const message = active[key] ?? fallback[key] ?? key;
      return interpolate(message, params as InterpolationParams | undefined);
    },
    has(key) { return active[key] !== undefined || fallback[key] !== undefined; },
  };
}

export interface LocaleStore {
  getLocale(): Locale;
  setLocale(locale: LocaleInput): Locale;
  subscribe(listener: (locale: Locale) => void): () => void;
  translator(): Translator;
}

export interface I18nContextValue extends Translator {
  setLocale(locale: LocaleInput): Locale;
}

const I18nContext = createContext<I18nContextValue | null>(null);
const defaultContext: I18nContextValue = { ...createTranslator(DEFAULT_LOCALE), setLocale: locale => normalizeLocale(locale) };

export function I18nProvider({ children, initialLocale }: { children: ReactNode; initialLocale?: LocaleInput }) {
  const [locale, setLocaleState] = useState<Locale>(() => initialLocale === undefined ? readPersistedLocale() : normalizeLocale(initialLocale));
  const setLocale = useCallback((next: LocaleInput) => {
    const normalized = persistLocale(next);
    setLocaleState(normalized);
    return normalized;
  }, []);
  const translator = useMemo(() => createTranslator(locale), [locale]);
  const value = useMemo<I18nContextValue>(() => ({ ...translator, setLocale }), [setLocale, translator]);
  return createElement(I18nContext.Provider, { value }, children);
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext) ?? defaultContext;
}

/** Small app-shell seam for settings or React context to own locale changes. */
export function createLocaleStore(options: TranslatorOptions = {}): LocaleStore {
  let locale = readPersistedLocale(options.storage, options.storageKey);
  const listeners = new Set<(next: Locale) => void>();
  return {
    getLocale: () => locale,
    setLocale(next) {
      locale = persistLocale(next, options.storage, options.storageKey);
      listeners.forEach(listener => listener(locale));
      return locale;
    },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    translator: () => createTranslator(locale, options),
  };
}
