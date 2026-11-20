import { describe, expect, it, vi } from "vitest";
import { filamentIdentity, filamentMatches, materialDisplayName } from "../utils/filamentIdentity";
import { localLutIdentity } from "../utils/libraryFilamentIdentity";

describe("filament packaging and search", () => {
  it("uses the original Polymaker artwork only for Panchroma PLA during the approved term", () => {
    const display = { series: "Panchroma", material_type: "PLA" };
    const logo = "https://www.luminastudio.com.cn/logos/polymaker-teal.svg";
    try {
      vi.setSystemTime(new Date("2026-11-18T10:00:00Z"));
      expect(filamentIdentity("Polymaker", "Panchroma 品红", "zh", display).logo).toBe(logo);
      expect(localLutIdentity(undefined, "PLA Panchroma · RYBW", "en", {
        ...display, manufacturer: "Polymaker",
      }).logo).toBe(logo);
      expect(localLutIdentity(undefined, "Mixed PLA", "en", {
        ...display, manufacturer: "Polymaker", filaments: [
          { ...display, brand: "Polymaker" },
          { ...display, brand: "Polymaker", series: "Basic" },
        ],
      }).logo).toBeUndefined();
      expect(filamentIdentity("Polymaker", "Basic White", "en", { ...display, series: "Basic" }).logo).toBeUndefined();
      expect(filamentIdentity("Polymaker", "Panchroma", "en", { ...display, material_type: "PETG" }).logo).toBeUndefined();
      expect(filamentIdentity("Polymaker", "", "en")).toMatchObject({ brand: "Polymaker", logo: undefined });
      vi.setSystemTime(new Date("2027-11-18T09:06:40Z"));
      expect(filamentIdentity("Polymaker", "Panchroma 品红", "zh", display).logo).toBe(logo);
      vi.setSystemTime(new Date("2027-11-18T09:06:41Z"));
      expect(filamentIdentity("Polymaker", "Panchroma 品红", "zh", display).logo).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("resolves each packaging market independently of UI language", () => {
    const original = "Bambu PLA Basic 黑色";
    const intl = filamentIdentity("拓竹", original, "zh", undefined, "INTL");
    const cn = filamentIdentity("Bambu-Lab", original, "en", undefined, "CN");
    expect(intl).toMatchObject({ name: "PLA Basic Black", originalName: original, brand: "Bambu Lab", productCode: "10101" });
    expect(cn).toMatchObject({ name: "PLA Basic 黑色", originalName: original, brand: "拓竹", logo: intl.logo });
    expect(intl.logo).toBeTruthy();
    for (const q of ["10101", "拓竹 black", "ＢＡＭＢＵ　黑色", "PLA_BASIC Black"]) {
      expect(filamentMatches(q, cn.searchText)).toBe(true);
      expect(filamentMatches(q, intl.searchText)).toBe(true);
    }
    expect(filamentMatches("10100", intl.searchText)).toBe(false);
  });

  it("returns an evidenced code for the detail view and preserves the catalog's spelling", () => {
    expect(filamentIdentity("彩多屋", "PLA AC3517国旗红", "en").productCode).toBe("AC3517");
    expect(filamentIdentity("彩多屋", "PLA AC3517国旗红", "en", { color_code: "ac3517", sku: "Refill-001" }).productCode).toBe("ac3517");
    expect(filamentIdentity("拓竹", "Bambu PLA Basic 黑色", "zh", { sku: "Bbl-001-Refill" }).productCode).toBe("Bbl-001-Refill");
    expect(filamentIdentity("拓竹", "Calibration", "zh", { fila_color_code: 10203 }).productCode).toBe("10203");
    expect(filamentIdentity("Unknown", "PLA Blue 10101", "en", { sku: [], color_code: {} }).productCode).toBeUndefined();
    expect(filamentIdentity("赛纳", "赛纳PETG深红色", "en").productCode).toBeUndefined();
  });

  it.each([
    ["PLA", "Basic", "品红", "Magenta", "10202"],
    ["PLA", "Basic", "南瓜橙", "Pumpkin Orange", "10301"],
    ["PETG", "Basic", "白色", "White", "30106"],
    ["PLA", "Matte", "暗夜蓝", "Dark Blue", "11602"],
  ])("localizes structured %s %s colors consistently across packaging markets", (materialType, series, color, english, code) => {
    const name = `${series} ${color}`;
    const display = { material_type: materialType, series, color_name: color };
    const intl = materialDisplayName(filamentIdentity("Bambu Lab", name, "zh", display, "INTL"));
    const cn = materialDisplayName(filamentIdentity("Bambu Lab", name, "en", display, "CN"));
    expect(intl).toMatchObject({ name: `${series} ${english}`, colorName: english, productCode: code, originalName: name });
    expect(cn).toMatchObject({ name, colorName: color, productCode: code, originalName: name });
    expect(filamentMatches(`${color} ${english} ${code}`, intl.searchText)).toBe(true);
  });

  it("keeps explicit regional names while localizing common descriptors without assigning a product", () => {
    const display = { material_type: "PLA", series: "Basic", color_name: "深蓝色" };
    expect(filamentIdentity("Bambu Lab", "Basic 深蓝色", "zh", display, "INTL"))
      .toMatchObject({ name: "Basic Dark blue", colorName: "Dark blue", productCode: undefined });
    expect(filamentIdentity("Bambu Lab", "Basic 深蓝色", "en", {
      ...display, market_names: { INTL: "Special packaging" },
    }, "INTL").name).toBe("Special packaging");
    expect(filamentIdentity("Bambu Lab", "作者特别版", "en", display, "INTL").name).toBe("作者特别版");
    expect(filamentIdentity("KARVAX", "Basic 烟笼紫霞", "en", {
      material_type: "PLA", series: "Basic", color_name: "烟笼紫霞",
    }, "INTL").name).toBe("Basic 烟笼紫霞");
    expect(filamentIdentity("wjxc", "PLA · CMYWGK", "zh", {
      brand_identity: { key: "wjxc", label: "wjxc" },
    }, "CN")).toMatchObject({ brand: "无境新材" });
    expect(filamentIdentity("wjxc", "PLA · CMYWGK", "zh", {
      brand_identity: { key: "wjxc", label: "wjxc" },
    }, "CN").logo).toBeTruthy();
    expect(filamentIdentity("Bambu Lab", "Basic 黑色", "en", {
      material_type: "PLA", series: "Basic", color_name: "黑色", color_code: "10203",
    }, "INTL").name).toBe("Basic 黑色");
  });

  it("localizes plain and glow color descriptors without requiring a series or inventing a SKU", () => {
    expect(filamentIdentity("Alchemakes", "白色", "zh", {
      material_type: "PETG", color_name: "白色",
    }, "INTL")).toMatchObject({ name: "White", colorName: "White", productCode: undefined });
    expect(filamentIdentity("Bambu Lab", "Basic 夜光蓝", "zh", {
      material_type: "PLA", series: "Basic", color_name: "夜光蓝",
    }, "INTL")).toMatchObject({ name: "Basic Glow blue", colorName: "Glow blue", productCode: undefined });
  });

  it("does not invent a product series from a code on an incomplete legacy record", () => {
    const display = { material_type: "PLA", color_name: "红色", color_code: "16200" };
    expect(filamentIdentity("Bambu Lab", "红色", "zh", display, "INTL"))
      .toMatchObject({ name: "红色", productCode: "16200", series: undefined });
    expect(filamentIdentity("Bambu Lab", "红色", "zh", { ...display, material_type: "PETG" }, "INTL").name).toBe("红色");
    expect(filamentIdentity("Bambu Lab", "PLA red 16200", "en").name).toBe("PLA red 16200");
    expect(filamentIdentity("Bambu Lab", "Calibration", "en", { fila_color_code: 10203 }))
      .toMatchObject({ name: "Calibration", series: undefined });
    expect(filamentIdentity("彩多屋", "Measurement", "en", { color_code: "AC3517" }))
      .toMatchObject({ name: "Measurement", series: undefined });
  });

  it("uses a confirmed series without letting a conflicting old number turn Basic into Lite", () => {
    expect(filamentIdentity("Bambu Lab", "Basic 红色", "zh", {
      material_type: "PLA", series: "Basic", color_name: "红色", color_code: "16200",
    }, "INTL")).toMatchObject({ name: "Basic 红色", series: "Basic" });
    expect(filamentIdentity("Bambu Lab", "Basic 红色", "zh", {
      material_type: "PLA", series: "Basic", color_name: "红色",
    }, "INTL")).toMatchObject({ name: "Basic Red", series: "Basic", productCode: "10200" });
  });

  it.each([
    ["Basic 蓝紫色", "Basic", "蓝紫色", "Basic Blue-violet"],
    ["蓝色 L", "", "蓝色 L", "Blue L"],
  ])("translates common descriptors while retaining a literal calibration tag in %s", (name, series, colorName, english) => {
    const display = { material_type: "PLA", series, color_name: colorName };
    expect(filamentIdentity("Bambu Lab", name, "zh", display, "INTL"))
      .toMatchObject({ name: english, productCode: undefined });
    expect(filamentIdentity("Bambu Lab", name, "en", display, "CN").name).toBe(name);
  });

  it("matches an exact manufacturer code on an original calibration with attribution", () => {
    const original = "拓竹 PLA_BASIC 粉色（pink 10203）_自然光_Rean";
    const pink = filamentIdentity("拓竹", original, "en");
    expect(pink).toMatchObject({ name: "PLA Basic Pink", originalName: original });
    expect(filamentMatches("REAN 10203 自然光", pink.searchText)).toBe(true);
    const gray = filamentIdentity("Bambu", "拓竹PLA Basic 蓝灰 by昏惩", "en");
    expect(gray.name).toBe("PLA Basic Blue Gray");
    expect(filamentMatches("10602 昏惩", gray.searchText)).toBe(true);
  });

  it("uses the brand and full grade, without fitting an official color to a similar name or RGB", () => {
    expect(filamentIdentity("Bambu", "PLA Matte 暗夜蓝", "en").name).toBe("PLA Matte Dark Blue");
    expect(filamentIdentity("Bambu", "PLA Basic 深蓝色", "en").name).toBe("PLA Basic 深蓝色");
    expect(filamentIdentity("SUNLU", "PLA Basic 黑色", "en", { rgb: [0, 0, 0] }).name).toBe("PLA Basic 黑色");
    expect(filamentIdentity("拓竹", "PETG HF 白色", "en", { fila_color_code: "10100" }).name).toBe("PETG HF 白色");
    expect(filamentIdentity("拓竹", "PLA Basic 黑色", "en", { color_code: "10203" }).name).toBe("PLA Basic 黑色");
    expect(filamentIdentity("拓竹", "PLA Basic 黑色 (10203)", "en").name).toBe("PLA Basic 黑色 (10203)");
    expect(filamentIdentity("拓竹", "PLA Basic 黑色 (10101) + 粉色 (10203)", "en").name).toContain("黑色");
    expect(filamentIdentity("拓竹", "Calibration", "en", { fila_color_code: 10203 }).name).toBe("Calibration");
    expect(filamentIdentity("彩多屋", "PETG sample", "en", { sku: "AC3517" }).name).toBe("PETG sample");
    expect(filamentIdentity("彩多屋", "Measurement", "en", { color_code: "AC3517", material_type: "PETG" }).name).toBe("Measurement");
    expect(filamentIdentity("拓竹", "Bambu PLA Basic 亮黑色", "en").name).toBe("Bambu PLA Basic 亮黑色");
    expect(filamentMatches("10101", filamentIdentity("拓竹", "PLA Basic 黑色 (studio effect)", "en").searchText)).toBe(false);
  });

  it.each([
    ["PLA AC3517国旗红", "PLA Ruby AC3517", "国旗红 Ruby AC3517"],
    ["PLA AC6050樱粉色", "PLA Sakura Pink AC6050", "樱粉色 sakura"],
    ["PLA AC2010芒果黄", "PLA Mango Yellow AC2010", "芒果黄 mango"],
    ["PLA AC2925青色", "PLA Cyan AC2925", "青色 cyan"],
    ["PLA AC421浅灰色", "PLA Light Gray AC421", "浅灰色 gray"],
  ])("uses the same CaiLab color code for the registry and manufacturer spelling of %s", (original, name, q) => {
    const item = filamentIdentity("彩多屋", original, "en");
    expect(item).toMatchObject({ originalName: original, name, brand: "CAILAB" });
    expect(filamentMatches(q, item.searchText)).toBe(true);
    expect(filamentIdentity("彩多屋", original.replace("PLA", "PETG"), "en").name).toBe(original.replace("PLA", "PETG"));
    expect(filamentIdentity("无境新材", original, "en").name).toBe(original);
  });

  it("uses display metadata for the chosen market and searches each label and code", () => {
    const display = {
      market_names: { CN: "中文包装", INTL: { zh: "国际包装", en: "International packaging" } },
      localized_names: { en: "Catalog translation", "zh-CN": "目录译名" },
      aliases: ["Shop edition", null],
      sku: "SAMPLE-55",
      brand_identity: { key: "Example Brand", label: "品牌", names: { en: "Example Brand", "zh-CN": "示例品牌" }, search_terms: ["shili"] },
    };
    const selected = filamentIdentity("brand", "测量原名", "zh", display, "INTL");
    expect(selected).toMatchObject({ name: "国际包装", originalName: "测量原名", brand: "Example Brand" });
    expect(filamentMatches("shili 目录译名 SAMPLE55 SHOP 包装", selected.searchText)).toBe(true);
    expect(filamentIdentity("brand", "测量原名", "en", display, "CN")).toMatchObject({ name: "中文包装", brand: "示例品牌" });
    expect(filamentIdentity("brand", "测量原名", "zh", { localized_names: { en: "Catalog name" } }, "INTL").name).toBe("Catalog name");
  });

  it("preserves authors, custom labels and separate calibration runs when using descriptive colors", () => {
    const original = "赛纳PETG深红色 by MingDee";
    const item = filamentIdentity("赛纳", original, "en");
    expect(item).toMatchObject({ originalName: original, name: original, brand: "Sailner", colorDescription: "Dark red" });
    expect(filamentMatches("sailner dark red MingDee", item.searchText)).toBe(true);
    expect(filamentIdentity("Inslogic", "Inslogic PLA白色_20260521_161941", "en").colorDescription).toBe("White");
    expect(filamentIdentity("JAYO", "PETG Yellow", "zh").colorDescription).toBe("黄色");
    expect(filamentIdentity("无境新材", "无境新材 PLA 烟笼紫霞", "en").colorDescription).toBeUndefined();
    expect(filamentIdentity("三绿", "三绿PETG红色", "en").brand).toBe("SUNLU");
    expect(filamentIdentity("Unknown", "PLA 染红之霞", "en", { brand_identity: [], aliases: {}, localized_names: "wrong" }))
      .toMatchObject({ name: "PLA 染红之霞", originalName: "PLA 染红之霞", brand: "Unknown", logo: undefined });
    expect(filamentIdentity("Some SUNLU clone", "PLA", "en").logo).toBeUndefined();
    expect(filamentIdentity("拓竹", "Bambu PLA Basic 红色-青色-黑色", "en").colorDescription).toBeUndefined();
  });

  it("uses real partner packaging even when an older registry supplies a mixed-script brand label", () => {
    const item = filamentIdentity("Aliz爱丽兹", "PETG 克莱因蓝", "en", {
      brand_identity: { key: "aliz", names: { en: "Aliz爱丽兹" }, search_terms: ["ailizi"] },
    });
    expect(item.brand).toBe("Aliz");
    expect(item.colorDescription).toBe("Klein blue");
    expect(filamentMatches("ailizi 青", item.searchText)).toBe(false);
    expect(filamentMatches("ailizi Klein", item.searchText)).toBe(true);
    expect(filamentIdentity("Alchemakes", "PETG", "zh").brand).toBe("魔创");
    expect(filamentIdentity("爱乐酷ELEGOO", "PLA", "en").brand).toBe("ELEGOO");
    expect(filamentIdentity("三绿", "PLA", "en").logo).not.toBe(filamentIdentity("JAYO", "PLA", "en").logo);
  });
});
