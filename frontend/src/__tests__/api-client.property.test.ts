import { describe, it, expect } from "vitest";
import fc from "fast-check";
import apiClient from "../api/client";

describe("Feature: thread-separation-upgrade, API 客户端 baseURL 验证", () => {
  /**
   * Validates: Requirements 3.2, 3.3
   * The default baseURL should be a relative path "/api", not a hardcoded absolute URL.
   */
  it("apiClient baseURL defaults to relative /api path", () => {
    const baseURL = apiClient.defaults.baseURL;
    expect(baseURL).toBe("/api");
  });

  it("apiClient baseURL does not contain localhost or hardcoded host", () => {
    const baseURL = apiClient.defaults.baseURL ?? "";
    expect(baseURL).not.toContain("localhost");
    expect(baseURL).not.toContain("http://");
    expect(baseURL).not.toContain("https://");
  });

  /**
   * Validates: Requirements 3.2
   * For any relative path string, the constructed URL should start with the baseURL.
   */
  it("apiClient.getUri({ url: path }) always starts with baseURL", () => {
    const baseURL = "/api";
    const pathChars = "/abcdefghijklmnopqrstuvwxyz0123456789-_".split("");
    const pathArb = fc
      .array(fc.constantFrom(...pathChars), { minLength: 1, maxLength: 50 })
      .map((chars) => chars.join(""));

    fc.assert(
      fc.property(
        pathArb,
        (path) => {
          const uri = apiClient.getUri({ url: path });
          expect(uri).toMatch(
            new RegExp(
              `^${baseURL.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`
            )
          );
        }
      ),
      { numRuns: 100 }
    );
  });
});
