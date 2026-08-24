import { describe, expect, it } from 'vitest';
import { createLocaleStore, createTranslator, normalizeLocale, persistLocale, readPersistedLocale } from './index';

function storage(initial: string | null = null) {
  let value = initial;
  return { getItem: () => value, setItem: (_key: string, next: string) => { value = next; }, value: () => value };
}

describe('i18n catalog and translator', () => {
  it('serves Chinese by default and English on request', () => {
    expect(createTranslator().t('app.nav.device')).toBe('设备控制');
    expect(createTranslator('en').t('app.nav.device')).toBe('Device control');
  });

  it('interpolates typed catalog values', () => {
    const translator = createTranslator('en');
    expect(translator.t('device.connection.attempt', { count: 3 })).toBe('Attempt 3');
    expect(translator.t('common.label.minutesSeconds', { minutes: 2, seconds: 4 })).toBe('2m 4s');
  });

  it('falls back from an incomplete active catalog to Chinese, then to the key', () => {
    const translator = createTranslator('en', { catalogs: { zh: { 'app.nav.device': '设备控制' }, en: {} } });
    expect(translator.t('app.nav.device')).toBe('设备控制');
    expect(translator.t('settings.title')).toBe('settings.title');
    expect(translator.has('app.nav.device')).toBe(true);
  });

  it('normalizes regional/case variants and defaults unsupported input to zh', () => {
    expect(normalizeLocale('EN_us')).toBe('en');
    expect(normalizeLocale('zh-Hans-CN')).toBe('zh');
    expect(normalizeLocale('fr-FR')).toBe('zh');
    expect(normalizeLocale(undefined)).toBe('zh');
  });

  it('reads and writes the persisted locale defensively', () => {
    const store = storage('en');
    expect(readPersistedLocale(store)).toBe('en');
    expect(persistLocale('zh-CN', store)).toBe('zh');
    expect(store.value()).toBe('zh');
    expect(createTranslator(undefined, { storage: storage('en') }).locale).toBe('en');
    expect(createTranslator({ locale: 'en-US', storage: storage('zh') }).locale).toBe('en');
  });

  it('notifies a locale store and creates a translator for the current locale', () => {
    const store = createLocaleStore({ storage: storage('zh') });
    const seen: string[] = [];
    const unsubscribe = store.subscribe(locale => seen.push(locale));
    expect(store.setLocale('en-US')).toBe('en');
    expect(store.translator().t('settings.title')).toBe('Settings');
    unsubscribe();
    store.setLocale('zh');
    expect(seen).toEqual(['en']);
  });
});
