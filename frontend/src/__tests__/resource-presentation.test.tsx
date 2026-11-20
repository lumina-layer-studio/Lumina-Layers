import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { filamentIdentity, materialDisplayName } from "../utils/filamentIdentity";
import { localLutIdentity } from "../utils/libraryFilamentIdentity";
import { resourceColorMode, resourceColors } from "../utils/resourcePresentation";
import { LibraryIdentity } from "../components/ui/LibraryDetails";
import CloudLibraryPreview from "../components/ui/CloudLibraryPreview";

describe("resource identity and details", () => {
  it("uses the same concise LUT title for offline filenames and catalog display fields", () => {
    const name = "Aliz&PETG&5color&红-黄-蓝-白-黑-20260304";
    const offline = localLutIdentity("Aliz", name, "zh", undefined, "CN");
    const cloud = localLutIdentity(undefined, "uuid.json", "zh", { name, manufacturer: "Aliz" }, "CN");
    expect(offline.name).toBe("PETG · 5 色");
    expect(cloud).toEqual(offline);
    expect(offline).toMatchObject({ originalName: name, brand: "爱丽兹", materialType: "PETG" });
    expect(localLutIdentity("Aliz", "Aliz&4色PETG&CMYW", "en").name).toBe("PETG · CMYW");
    expect(localLutIdentity("Aliz", "Aliz&PLA&4色CMYW&20260223", "zh").name).toBe("PLA · CMYW");
    expect(localLutIdentity("Sailner", "赛纳&4色PETG&CMYW-品红-青-黄-白", "zh").name).toBe("PETG · CMYW");
    expect(localLutIdentity("REBIRTH3D", "瑞贝思&6色&PLA&红黄蓝白黑绿&20260401", "zh").name).toBe("PLA · 6 色");
    const title = "Aliz&PETG&作者特别版";
    expect(localLutIdentity("Aliz", title, "zh").name).toBe(title);
    expect(localLutIdentity("Custom", "Bambulab&PLA&8色", "en").brand).toBe("Bambu Lab");
    expect(localLutIdentity("Sailner", "Bambulab&PLA&8色", "en").brand).toBe("Sailner");
    expect(localLutIdentity("Aliz", "Mixed", "zh", { filaments: [
      { brand: "Aliz" }, { brand: "Bambu Lab" },
    ] })).toMatchObject({ brand: "混合品牌", logo: undefined });
    expect(resourceColorMode("4-Color (RYBW)", "zh")).toBe("4 色 (RYBW)");
  });

  it("keeps original attribution searchable while making single-filament titles concise", () => {
    const original = "赛纳PETG深红色 by MingDee";
    const identity = materialDisplayName(filamentIdentity("赛纳", original, "zh"));
    expect(identity.name).toBe("PETG深红色");
    expect(identity.originalName).toBe(original);
    expect(identity.searchText).toContain("MingDee");
    expect(materialDisplayName(filamentIdentity("Some SUNLU clone", "PLA 色卡", "en")).name).toBe("PLA 色卡");
  });

  it.each([
    ["Bambu Lab", "Basic 红色", "Basic 红色"],
    ["Bambu Lab", "Bamboo 试样", "Bamboo 试样"],
    ["Bambu Lab", "拓竹绿", "拓竹绿"],
    ["Aliz", "Alizarin 红色", "Alizarin 红色"],
    ["Bambu Lab", "Bambu Basic 红色", "Basic 红色"],
    ["Bambu Lab", "BambuPLA Basic 深蓝色", "PLA Basic 深蓝色"],
    ["Bambu Lab", "拓竹/拓竹PLA Basic 深蓝色", "PLA Basic 深蓝色"],
    ["Bambu Lab", "ba PLA Basic 深蓝色", "PLA Basic 深蓝色"],
    ["Sailner", "赛纳PETG深红色", "PETG深红色"],
  ])("strips only complete brand prefixes from %s / %s", (brand, original, expected) => {
    for (const language of ["zh", "en"] as const) {
      const identity = materialDisplayName(filamentIdentity(brand, original, language));
      expect(identity.name).toBe(expected);
      expect(identity.originalName).toBe(original);
      expect(identity.searchText).toContain(original);
    }
  });

  it("preserves explicit filament order and never treats LUT calibration pixels as material colors", () => {
    expect(resourceColors({ kind: "luts", name: "Aliz&8色PLA", mode: "8-color" }, "zh")).toEqual([]);
    expect(resourceColors({ kind: "luts", name: "PETG 红-黄-蓝-白-黑" }, "en").map((c) => c.label))
      .toEqual(["Red", "Yellow", "Blue", "White", "Black"]);
    expect(resourceColors({ kind: "luts", mode: "BW" }, "en").map((c) => c.label)).toEqual(["Black", "White"]);
    expect(resourceColors({ kind: "luts", display: { palette_rgb: [[1, 2, 3], [4, 5, 6]] } }, "en"))
      .toEqual([{ label: "Channel 1", hex: "#010203" }, { label: "Channel 2", hex: "#040506" }]);
    expect(resourceColors({ kind: "luts", display: { filaments: [
      { slot: 1, brand: "Bambu Lab", color_name: "White", color_hex: "#fefefe" },
      { slot: 0, brand: "Aliz", color_name: "Red", color_hex: "#ee4433" },
    ] } }, "en").map((c) => c.label)).toEqual(["Red", "White"]);
    expect(resourceColors({ kind: "luts", mode: "8-color",
      name: "赛纳sailner&8色PETG-深红-深黄-深蓝-品红-青-白-浅绿-黑(华溪第二版)" }, "zh")).toEqual([]);
    expect(resourceColors({ kind: "luts", mode: "8-color", name: "Aliz&PLA&8色红-黄-蓝-品红-青-白-绿-黑&20260213" }, "zh"))
      .toHaveLength(8);
    expect(resourceColors({ kind: "luts", mode: "6-color", name: "测试红-黄-蓝-白" }, "zh")).toEqual([]);
    expect(resourceColors({ kind: "luts", mode: "6-color", name: "测试&RYBW" }, "zh")).toEqual([]);
  });

  it("keeps long source names and regional purchase links in details only", () => {
    const identity = filamentIdentity("Bambu Lab", "原始实测档案", "zh", {
      market_names: { CN: "PLA Basic 黑色" }, series: "PLA Basic", contributor_name: "旧资料署名",
      purchase_links: [
        { label: "国内商品页", market: "CN", url: "https://shop.example.cn/black" },
        { label: "International", market: "INTL", url: "https://shop.example.com/black" },
        { label: "unsafe", url: "javascript:alert(1)" },
        { label: "credentials", url: "https://user:password@shop.example.cn/" },
        { label: "duplicate", url: "https://shop.example.cn/black" },
      ],
    }, "CN");
    const thumbnail = { kind: "materials" as const };
    render(<CloudLibraryPreview resetKey="one" toolbar={null} items={[{
      key: "one", ...identity, subtitle: identity.brand, state: "available", thumbnail,
      detail: <LibraryIdentity {...identity} subtitle={identity.brand} thumbnail={thumbnail} />,
    }]} />);
    expect(screen.queryByText("原始实测档案")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /PLA Basic 黑色/ }));
    const detail = screen.getByRole("complementary");
    expect(within(detail).getByText("原始实测档案")).toBeInTheDocument();
    expect(within(detail).getByText("旧资料署名")).toBeInTheDocument();
    const links = within(detail).getAllByRole("link");
    expect(links).toHaveLength(1);
    const purchase = within(detail).getByRole("link", { name: /shop.example.cn/ });
    expect(purchase).toHaveAttribute("href", "https://shop.example.cn/black");
    expect(purchase).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(detail).getByText("未标注")).toBeInTheDocument();
    expect(links.find(link => link.getAttribute("href") === "/data-license.html")).toBeUndefined();
  });

  it("keeps unmarked, CC BY and Lumina resource licenses distinct in actual details", () => {
    render(<>
      <section aria-label="Historical LUT"><LibraryIdentity name="Historical LUT" subtitle="Historical" thumbnail={{ kind: "luts" }} /></section>
      <section aria-label="CC BY LUT"><LibraryIdentity name="CC BY LUT" subtitle="CC BY" thumbnail={{ kind: "luts", display: { license: "CC-BY-4.0" } }} /></section>
      <section aria-label="Lumina LUT"><LibraryIdentity name="Lumina LUT" subtitle="Lumina" thumbnail={{ kind: "luts", display: { license: "LicenseRef-Lumina-Data-1.0" } }} /></section>
    </>);
    const historical = within(screen.getByRole("region", { name: "Historical LUT" }));
    expect(historical.getByText("未标注")).toBeInTheDocument();
    expect(historical.queryByRole("link")).toBeNull();
    expect(within(screen.getByRole("region", { name: "CC BY LUT" })).getByRole("link", { name: "CC-BY-4.0" }))
      .toHaveAttribute("href", "https://creativecommons.org/licenses/by/4.0/");
    expect(within(screen.getByRole("region", { name: "Lumina LUT" })).getByRole("link", { name: "Lumina 数据使用协议 1.0" }))
      .toHaveAttribute("href", "/data-license.html");
  });

  it("adapts material color details and LUT slot details without changing slot order", () => {
    const material = filamentIdentity("Aliz", "Sample", "zh", { color_name: "包装红", series: "PETG HF" });
    const { unmount } = render(<LibraryIdentity {...material} subtitle="Aliz" thumbnail={{ kind: "materials" }} />);
    expect(screen.getByText("包装红")).toBeInTheDocument();
    expect(screen.getByText("PETG HF")).toBeInTheDocument();
    unmount();
    render(<LibraryIdentity name="Mixed" subtitle="混合品牌" thumbnail={{ kind: "luts", display: {
      filaments: [
        { slot: 1, brand: "Bambu Lab", material_name: "White", series: "PLA Basic", color_code: "00100" },
        { slot: 0, brand: "Aliz", material_name: "Red", series: "PLA Pro", color_code: "00200" },
      ],
    } }} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Red");
    expect(rows[0]).toHaveTextContent("PLA Pro");
    expect(rows[0]).toHaveTextContent("00200");
    expect(rows[1]).toHaveTextContent("White");
  });

  it.each(["materials", "luts"] as const)("shows the retained source name for a normalized %s record", (kind) => {
    render(<LibraryIdentity name="统一商品名称" originalName="规范后的颜色名" subtitle="Brand"
      thumbnail={{ kind, display: { original_name: "PLA red 16200 by 原作者" } }} />);
    expect(screen.getByText("PLA red 16200 by 原作者")).toBeInTheDocument();
    expect(screen.queryByText("规范后的颜色名")).toBeNull();
  });

  it("shows Polymaker support notice and orders product attributes ahead of usage license", () => {
    try {
      vi.setSystemTime(new Date("2026-11-19T00:00:00Z"));
      const identity = filamentIdentity("Polymaker", "Panchroma PLA Magenta", "zh", {
        series: "Panchroma",
        material_type: "PLA",
        color_name: "品红",
        description: "高饱和度品红测试耗材，适合四色 CMYW 混色方案。",
      }, "CN");
      const { container } = render(
        <LibraryIdentity
          {...identity}
          subtitle="Polymaker · PLA"
          thumbnail={{
            kind: "materials",
            display: {
              attribution: {
                relationship: "adapted",
                original_author: "Polymaker Team",
                rights_basis: "Authorized test profile under Lumina Data License 1.0.",
                source: { resource_id: "mat_7b5c34be46654f6c", revision_id: "rev_dd1d19bb279144cc" },
              },
            },
          }}
        />,
      );
      expect(screen.getByText("适配与支持")).toBeInTheDocument();
      expect(screen.getByText(/Panchroma PLA 适配中/)).toBeInTheDocument();
      expect(screen.getByText(/不代表 Polymaker 对 Lumina Studio 软件整体或打印效果的认证或保证/)).toBeInTheDocument();
      const terms = Array.from(container.querySelectorAll("dt")).map((node) => node.textContent);
      expect(terms.indexOf("产品系列")).toBeGreaterThanOrEqual(0);
      expect(terms.indexOf("颜色名称")).toBeGreaterThan(terms.indexOf("产品系列"));
      expect(terms.indexOf("使用许可")).toBeGreaterThan(terms.indexOf("颜色名称"));
      const revisionDd = screen.getByText("mat_7b5c34be46654f6c · rev_dd1d19bb279144cc");
      expect(revisionDd.className).not.toContain("text-right");
    } finally {
      vi.useRealTimers();
    }
  });
});
