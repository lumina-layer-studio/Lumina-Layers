/**
 * Property-Based Test: WIDGET_REGISTRY titleKey 与 i18n 一致性
 * WIDGET_REGISTRY titleKey consistency with i18n translations.
 *
 * Feature: granular-floating-widgets, Property 3: WIDGET_REGISTRY titleKey 与 i18n 一致性
 * **Validates: Requirements 8.1, 8.3**
 *
 * For any entry in WIDGET_REGISTRY, its titleKey should exist in the
 * translations object and contain both zh and en translation values
 * (non-empty strings).
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { WIDGET_REGISTRY } from '../stores/widgetStore';
import { translations } from '../i18n/translations';

describe('Granular Floating Widgets — Property-Based Tests', () => {
  // Feature: granular-floating-widgets, Property 3: WIDGET_REGISTRY titleKey 与 i18n 一致性
  describe('Property 3: WIDGET_REGISTRY titleKey 与 i18n 一致性', () => {
    // Arbitrary that picks a random entry from WIDGET_REGISTRY
    const registryEntryArb = fc.constantFrom(...WIDGET_REGISTRY);

    it('every WIDGET_REGISTRY titleKey exists in translations with non-empty zh and en values', () => {
      // **Validates: Requirements 8.1, 8.3**
      fc.assert(
        fc.property(registryEntryArb, (entry) => {
          const { titleKey } = entry;

          // titleKey must exist in translations
          expect(translations).toHaveProperty(titleKey);

          const translation = translations[titleKey];

          // Must have zh key with non-empty string
          expect(translation).toHaveProperty('zh');
          expect(typeof translation.zh).toBe('string');
          expect(translation.zh.length).toBeGreaterThan(0);

          // Must have en key with non-empty string
          expect(translation).toHaveProperty('en');
          expect(typeof translation.en).toBe('string');
          expect(translation.en.length).toBeGreaterThan(0);
        }),
        { numRuns: 100 }
      );
    });
  });
});
