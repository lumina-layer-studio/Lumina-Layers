/**
 * Material picker dialog and selection persistence tests.
 * 耗材选择弹窗与选择持久化测试。
 */
import { useState } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SavedMaterialLibraryItem } from "../api/types";
import MaterialPickerDialog from "../components/ui/MaterialPickerDialog";
import { useConverterStore } from "../stores/converter";

function makeMaterial(
  overrides: Partial<SavedMaterialLibraryItem> & {
    material_name: string;
    directory_name: string;
  },
): SavedMaterialLibraryItem {
  return {
    material_file_url: `/api/files/${overrides.directory_name}-material`,
    stage_a_params_url: `/api/files/${overrides.directory_name}-stage-a`,
    created_at: "2026-04-17T00:00:00Z",
    updated_at: "2026-04-17T00:00:00Z",
    estimated_rgb: [200, 50, 50],
    layer_height_mm: 0.08,
    mean_delta_e: 1.4,
    verification_count: 1,
    verification_history: [],
    ...overrides,
  };
}

const SINGLE_TYPE_MATERIALS: SavedMaterialLibraryItem[] = [
  makeMaterial({
    material_name: "Red PLA",
    directory_name: "JAYO/red-pla",
    brand: "JAYO",
    material_type: "PLA",
    material_profile_id: "profile-red",
  }),
  makeMaterial({
    material_name: "Yellow PLA",
    directory_name: "jayo/yellow-pla",
    brand: "jayo",
    material_type: "PLA",
    material_profile_id: "profile-yellow",
    estimated_rgb: [240, 220, 60],
  }),
  makeMaterial({
    material_name: "Blue PLA",
    directory_name: "瑞贝思/blue-pla",
    brand: "瑞贝思",
    material_type: "PLA",
    material_profile_id: "profile-blue",
    estimated_rgb: [40, 80, 200],
  }),
];

const PROFILE_MATERIALS: SavedMaterialLibraryItem[] = [
  makeMaterial({
    material_name: "PLA Basic Red",
    directory_name: "JAYO/pla-red-alice",
    brand: "JAYO",
    material_type: "PLA",
    material_product_id: "product-pla-red",
    material_profile_id: "profile-alice",
    contributor_name: "Alice",
    verification_count: 6,
  }),
  makeMaterial({
    material_name: "PLA Basic Red",
    directory_name: "JAYO/pla-red-bob",
    brand: "JAYO",
    material_type: "PLA",
    material_product_id: "product-pla-red",
    material_profile_id: "profile-bob",
    contributor_name: "Bob",
    verification_count: 3,
  }),
  makeMaterial({
    material_name: "Black PETG",
    directory_name: "Other/black-petg",
    brand: "Other",
    material_type: "PETG",
    material_profile_id: "profile-black",
    estimated_rgb: [15, 15, 18],
  }),
  makeMaterial({
    material_name: "Legacy Gold",
    directory_name: "legacy-gold",
    brand: null,
    material_type: null,
    material_profile_id: null,
    estimated_rgb: [205, 160, 55],
  }),
];

function renderPicker(
  overrides: Partial<React.ComponentProps<typeof MaterialPickerDialog>> = {},
) {
  const props: React.ComponentProps<typeof MaterialPickerDialog> = {
    open: true,
    materials: SINGLE_TYPE_MATERIALS,
    loading: false,
    initialSelected: [],
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  return { ...render(<MaterialPickerDialog {...props} />), props };
}

// Selected names also appear in the pinned strip; look for cards in the grid.
const cardGrid = () => screen.getByTestId("material-picker-card-grid");

describe("MaterialPickerDialog", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("renders nothing when closed", () => {
    const { container } = renderPicker({ open: false });
    expect(container.firstChild).toBeNull();
  });

  it("renders the accessible large dialog with type navigation and a two-column grid", () => {
    renderPicker();

    expect(
      screen.getByRole("dialog", { name: "选择耗材" }),
    ).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("tab", { name: "收藏" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "全部" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "PLA" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "PETG" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "其他" })).toBeInTheDocument();
    expect(
      screen.getByTestId("material-picker-brand-sidebar"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("material-picker-card-grid")).toHaveClass(
      "md:grid-cols-2",
    );
    expect(screen.getByTestId("material-picker-dialog")).toHaveClass(
      "w-[min(68rem,calc(100vw-3rem))]",
    );
    expect(screen.getByText("Red PLA")).toBeInTheDocument();
    expect(screen.getByText("Yellow PLA")).toBeInTheDocument();
    expect(screen.getByText("Blue PLA")).toBeInTheDocument();
  });

  it("commits only the final staged selection", () => {
    const onConfirm = vi.fn();
    renderPicker({
      initialSelected: ["JAYO/red-pla"],
      onConfirm,
    });

    fireEvent.click(
      screen.getByRole("button", { name: "选择 Yellow PLA" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "取消选择 Red PLA" }),
    );

    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(onConfirm).toHaveBeenCalledWith(["jayo/yellow-pla"]);
  });

  it("pins the selected materials above the list and lets them be removed there", () => {
    const onConfirm = vi.fn();
    renderPicker({ initialSelected: ["jayo/yellow-pla"], onConfirm });

    const strip = screen.getByTestId("material-picker-selected-strip");
    expect(within(strip).getByText("Yellow PLA")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "选择 Red PLA" }));
    // Listed in selection order.
    expect(within(strip).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Yellow PLA",
      "Red PLA",
    ]);

    fireEvent.click(within(strip).getByRole("button", { name: "移除 Yellow PLA" }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(onConfirm).toHaveBeenCalledWith(["JAYO/red-pla"]);
  });

  it("shows no selected strip content before anything is chosen", () => {
    renderPicker();
    expect(screen.getByTestId("material-picker-selected-strip")).toBeEmptyDOMElement();
  });

  it("toggles and commits a single material from the lower card details", () => {
    const onConfirm = vi.fn();
    renderPicker({
      materials: [
        {
          ...SINGLE_TYPE_MATERIALS[0],
          contributor_name: "Alice",
        },
      ],
      onConfirm,
    });

    fireEvent.click(screen.getByText("Alice"));
    expect(
      screen.getByRole("button", { name: "取消选择 Red PLA" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/已选耗材：1/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Alice"));
    expect(
      screen.getByRole("button", { name: "选择 Red PLA" }),
    ).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByText("Alice"));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(onConfirm).toHaveBeenCalledWith(["JAYO/red-pla"]);
  });

  it("keeps single-material favorite clicks independent from selection", () => {
    renderPicker({
      materials: [
        {
          ...SINGLE_TYPE_MATERIALS[0],
          contributor_name: "Alice",
        },
      ],
    });

    fireEvent.click(
      screen.getByRole("button", { name: "收藏 Red PLA（Alice）" }),
    );

    expect(
      screen.getByRole("button", { name: "取消收藏 Red PLA（Alice）" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "选择 Red PLA" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(/已选耗材：0/)).toBeInTheDocument();
  });

  it("keeps pointer selection free of a persistent inner focus ring", () => {
    renderPicker({
      initialSelected: ["JAYO/red-pla"],
    });

    const selectionButton = screen.getByRole("button", {
      name: "取消选择 Red PLA",
    });
    expect(selectionButton).not.toHaveClass("focus:ring-4");
    expect(selectionButton).toHaveClass("focus-visible:ring-2");
  });

  it("uses the same keyboard-only focus treatment for author profiles", () => {
    renderPicker({ materials: PROFILE_MATERIALS });

    const redCard = screen
      .getAllByTestId("material-picker-product-card")
      .find((card) => card.textContent?.includes("PLA Basic Red"));
    fireEvent.click(
      within(redCard!).getByRole("button", {
        name: "展开 PLA Basic Red 的档案",
      }),
    );
    const profileChoice = within(redCard!).getByRole("radio", {
      name: "选择 PLA Basic Red（Alice）档案",
    });
    expect(profileChoice).not.toHaveClass("focus:ring-4");
    expect(profileChoice).toHaveClass("focus-visible:ring-2");
  });

  it("gives a selected material a subtle whole-card treatment", () => {
    renderPicker({
      initialSelected: ["JAYO/red-pla"],
    });

    const selectedCard = within(cardGrid())
      .getByText("Red PLA")
      .closest('[data-testid="material-picker-product-card"]');
    const unselectedCard = within(cardGrid())
      .getByText("Yellow PLA")
      .closest('[data-testid="material-picker-product-card"]');

    expect(selectedCard).toHaveClass(
      "border-blue-300/80",
      "bg-blue-50/50",
      "drop-shadow-[0_1px_2px_var(--focus-ring)]",
    );
    expect(selectedCard).not.toHaveClass("bg-white/60");
    expect(unselectedCard).not.toHaveClass(
      "bg-blue-50/50",
      "drop-shadow-[0_1px_2px_var(--focus-ring)]",
    );
    expect(unselectedCard).toHaveClass("bg-white/60");
    expect(selectedCard).not.toHaveClass(
      "material-picker-card-select-effect",
    );
  });

  it("uses one whole-card effect without a redundant check indicator", () => {
    renderPicker();

    const selectionButton = screen.getByRole("button", {
      name: "选择 Red PLA",
    });
    const card = selectionButton.closest(
      '[data-testid="material-picker-product-card"]',
    );

    expect(selectionButton.querySelector("span.rounded-full")).toBeNull();
    expect(card).not.toHaveClass("material-picker-card-select-effect");

    fireEvent.click(selectionButton);
    expect(card).toHaveClass("material-picker-card-select-effect");

    fireEvent.click(
      screen.getByRole("button", { name: "取消选择 Red PLA" }),
    );
    expect(card).not.toHaveClass("material-picker-card-select-effect");
  });

  it("uses the same whole-card treatment for a selected author profile", () => {
    renderPicker({
      materials: PROFILE_MATERIALS,
      initialSelected: ["JAYO/pla-red-alice"],
    });

    const selectedCard = screen
      .getAllByTestId("material-picker-product-card")
      .find((card) => card.textContent?.includes("PLA Basic Red"));
    const unselectedCard = screen
      .getByText("Black PETG")
      .closest('[data-testid="material-picker-product-card"]');

    expect(selectedCard).toHaveClass(
      "border-blue-300/80",
      "bg-blue-50/50",
      "drop-shadow-[0_1px_2px_var(--focus-ring)]",
    );
    expect(selectedCard).not.toHaveClass("bg-white/60");
    expect(unselectedCard).not.toHaveClass(
      "bg-blue-50/50",
      "drop-shadow-[0_1px_2px_var(--focus-ring)]",
    );
    expect(unselectedCard).toHaveClass("bg-white/60");
    expect(selectedCard).not.toHaveClass(
      "material-picker-card-select-effect",
    );
  });

  it("plays the whole-card effect when a new author profile is selected", () => {
    renderPicker({ materials: PROFILE_MATERIALS });

    const redCard = screen
      .getAllByTestId("material-picker-product-card")
      .find((card) => card.textContent?.includes("PLA Basic Red"));
    fireEvent.click(
      within(redCard!).getByRole("button", {
        name: "展开 PLA Basic Red 的档案",
      }),
    );
    fireEvent.click(
      within(redCard!).getByRole("radio", {
        name: "选择 PLA Basic Red（Alice）档案",
      }),
    );

    expect(redCard).toHaveClass("material-picker-card-select-effect");
  });

  it("cancels without committing pending changes", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderPicker({ onConfirm, onCancel });

    fireEvent.click(screen.getByRole("button", { name: "选择 Red PLA" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("shows every brand neutrally, merges case-only duplicates, and has no more-brands bucket", () => {
    renderPicker();

    const brandLabels = screen
      .getAllByTestId("material-picker-brand-option")
      .map((option) => option.textContent);
    expect(brandLabels).toHaveLength(3);
    expect(brandLabels[0]).toMatch(/全部品牌.*3/);
    // Brand rows follow the host locale's collation (zh puts Han before
    // Latin), so compare them without pinning an order.
    expect(brandLabels.slice(1)).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/JAYO.*2/),
        expect.stringMatching(/瑞贝思.*1/),
      ]),
    );
    expect(screen.queryByText("更多品牌")).not.toBeInTheDocument();
  });

  it("leaves visible spacing between adjacent brand states", () => {
    renderPicker();

    const [firstBrandOption] = screen.getAllByTestId(
      "material-picker-brand-option",
    );
    expect(firstBrandOption.parentElement).toHaveClass("space-y-1");
  });

  it("keeps brand focus feedback inside the row and keyboard-only", () => {
    renderPicker();

    const brandOption = screen.getByRole("button", { name: "JAYO2" });
    expect(brandOption).not.toHaveClass("focus:ring-4");
    expect(brandOption).toHaveClass(
      "focus-visible:ring-2",
      "focus-visible:ring-inset",
    );
  });

  it("filters by type and brand without clearing hidden staged selections", () => {
    const onConfirm = vi.fn();
    renderPicker({
      materials: [...SINGLE_TYPE_MATERIALS, PROFILE_MATERIALS[2]],
      onConfirm,
    });

    fireEvent.click(screen.getByRole("button", { name: "选择 Red PLA" }));
    fireEvent.click(screen.getByRole("tab", { name: "PETG" }));
    expect(within(cardGrid()).queryByText("Red PLA")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "选择 Black PETG" }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "PLA" }));
    expect(within(cardGrid()).getByText("Red PLA")).toBeInTheDocument();
    expect(screen.getByText(/已选耗材：2/)).toBeInTheDocument();

    fireEvent.click(
      screen.getByTestId("material-picker-brand-option-brand:jayo"),
    );
    expect(within(cardGrid()).getByText("Red PLA")).toBeInTheDocument();
    expect(within(cardGrid()).queryByText("Blue PLA")).not.toBeInTheDocument();
  });

  it("groups same-product author profiles and requires an explicit profile choice", () => {
    const onConfirm = vi.fn();
    renderPicker({ materials: PROFILE_MATERIALS, onConfirm });

    const cards = screen.getAllByTestId("material-picker-product-card");
    expect(cards).toHaveLength(3);
    const redCard = cards.find((card) =>
      card.textContent?.includes("PLA Basic Red"),
    );
    expect(redCard).toBeDefined();
    expect(within(redCard!).getByText("2 份档案")).toBeInTheDocument();

    fireEvent.click(
      within(redCard!).getByRole("button", {
        name: "展开 PLA Basic Red 的档案",
      }),
    );
    expect(within(redCard!).getByText("Alice")).toBeInTheDocument();
    expect(within(redCard!).getByText("Bob")).toBeInTheDocument();

    fireEvent.click(
      within(redCard!).getByRole("radio", {
        name: "选择 PLA Basic Red（Alice）档案",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(onConfirm).toHaveBeenCalledWith(["JAYO/pla-red-alice"]);
  });

  it("shows calibration layer height on single-profile cards and omits missing values", () => {
    renderPicker({
      materials: [
        SINGLE_TYPE_MATERIALS[0],
        makeMaterial({
          material_name: "No Height PLA",
          directory_name: "Other/no-height-pla",
          brand: "Other",
          material_type: "PLA",
          material_profile_id: "profile-no-height",
          layer_height_mm: null,
        }),
      ],
    });

    const cards = screen.getAllByTestId("material-picker-product-card");
    const redCard = cards.find((card) => card.textContent?.includes("Red PLA"));
    const noHeightCard = cards.find((card) =>
      card.textContent?.includes("No Height PLA"),
    );

    expect(redCard).toHaveTextContent("JAYO · PLA · 0.08 mm");
    expect(noHeightCard).toHaveTextContent("Other · PLA");
    expect(noHeightCard).not.toHaveTextContent("mm");
  });

  it("shows grouped calibration layer heights in summaries and author rows", () => {
    const groupedMaterials = [
      { ...PROFILE_MATERIALS[0], layer_height_mm: 0.1 },
      { ...PROFILE_MATERIALS[1], layer_height_mm: 0.04 },
      {
        ...PROFILE_MATERIALS[1],
        directory_name: "JAYO/pla-red-carol",
        material_profile_id: "profile-carol",
        contributor_name: "Carol",
        layer_height_mm: 0.04,
      },
    ];
    renderPicker({ materials: groupedMaterials });

    const redCard = screen.getByTestId("material-picker-product-card");
    expect(redCard).toHaveTextContent("JAYO · PLA · 0.04 / 0.10 mm");

    fireEvent.click(
      within(redCard).getByRole("button", {
        name: "展开 PLA Basic Red 的档案",
      }),
    );

    const aliceRow = within(redCard)
      .getByRole("radio", {
        name: "选择 PLA Basic Red（Alice）档案",
      })
      .closest("div");
    const bobRow = within(redCard)
      .getByRole("radio", {
        name: "选择 PLA Basic Red（Bob）档案",
      })
      .closest("div");
    const carolRow = within(redCard)
      .getByRole("radio", {
        name: "选择 PLA Basic Red（Carol）档案",
      })
      .closest("div");

    expect(aliceRow).toHaveTextContent("0.10 mm");
    expect(bobRow).toHaveTextContent("0.04 mm");
    expect(carolRow).toHaveTextContent("0.04 mm");
  });

  it("keeps hidden sibling profiles mutually exclusive on the favorites tab", () => {
    const onConfirm = vi.fn();
    localStorage.setItem(
      "lumina_material_profile_favorites_v1",
      JSON.stringify(["profile:profile-bob"]),
    );
    renderPicker({
      materials: [
        { ...PROFILE_MATERIALS[0], layer_height_mm: 0.1 },
        { ...PROFILE_MATERIALS[1], layer_height_mm: 0.04 },
        ...PROFILE_MATERIALS.slice(2),
      ],
      initialSelected: ["JAYO/pla-red-alice"],
      onConfirm,
    });

    fireEvent.click(screen.getByRole("tab", { name: "收藏" }));
    const favoriteCard = screen.getByTestId("material-picker-product-card");
    expect(within(favoriteCard).queryByText("Alice")).not.toBeInTheDocument();
    expect(within(favoriteCard).getByText("Bob")).toBeInTheDocument();
    expect(favoriteCard).toHaveTextContent("JAYO · PLA · 0.04 mm");
    expect(favoriteCard).not.toHaveTextContent("0.10 mm");

    fireEvent.click(
      within(favoriteCard).getByRole("button", {
        name: "选择 PLA Basic Red",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "完成" }));

    expect(onConfirm).toHaveBeenCalledWith(["JAYO/pla-red-bob"]);
  });

  it("replaces an author profile at its existing material slot", () => {
    const onConfirm = vi.fn();
    renderPicker({
      materials: [
        SINGLE_TYPE_MATERIALS[2],
        PROFILE_MATERIALS[0],
        PROFILE_MATERIALS[1],
        SINGLE_TYPE_MATERIALS[1],
      ],
      initialSelected: [
        "瑞贝思/blue-pla",
        "JAYO/pla-red-alice",
        "JAYO/pla-red-bob",
        "jayo/yellow-pla",
      ],
      onConfirm,
    });

    const redCard = screen
      .getAllByTestId("material-picker-product-card")
      .find((card) => card.textContent?.includes("PLA Basic Red"));
    fireEvent.click(
      within(redCard!).getByRole("button", {
        name: "展开 PLA Basic Red 的档案",
      }),
    );
    fireEvent.click(
      within(redCard!).getByRole("radio", {
        name: "选择 PLA Basic Red（Bob）档案",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "完成" }));

    expect(onConfirm).toHaveBeenCalledWith([
      "瑞贝思/blue-pla",
      "JAYO/pla-red-bob",
      "jayo/yellow-pla",
    ]);
  });

  it("lets users favorite any number of author profiles independently", () => {
    renderPicker({ materials: PROFILE_MATERIALS });

    const redCard = screen
      .getAllByTestId("material-picker-product-card")
      .find((card) => card.textContent?.includes("PLA Basic Red"));
    fireEvent.click(
      within(redCard!).getByRole("button", {
        name: "展开 PLA Basic Red 的档案",
      }),
    );
    fireEvent.click(
      within(redCard!).getByRole("button", {
        name: "收藏 PLA Basic Red（Alice）",
      }),
    );
    fireEvent.click(
      within(redCard!).getByRole("button", {
        name: "收藏 PLA Basic Red（Bob）",
      }),
    );

    fireEvent.click(screen.getByRole("tab", { name: "收藏" }));
    const favoriteCard = screen.getByTestId("material-picker-product-card");
    expect(within(favoriteCard).getByText("Alice")).toBeInTheDocument();
    expect(within(favoriteCard).getByText("Bob")).toBeInTheDocument();
    expect(
      within(favoriteCard).getAllByRole("button", {
        name: /取消收藏 PLA Basic Red/,
      }),
    ).toHaveLength(2);

    expect(
      JSON.parse(
        localStorage.getItem("lumina_material_profile_favorites_v1") ?? "[]",
      ),
    ).toEqual(["profile:profile-alice", "profile:profile-bob"]);
  });

  it("searches author names and reveals the matching profile", () => {
    renderPicker({ materials: PROFILE_MATERIALS });

    fireEvent.change(screen.getByTestId("material-picker-search-input"), {
      target: { value: "Alice" },
    });

    expect(screen.getByText("PLA Basic Red")).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.queryByText("Black PETG")).not.toBeInTheDocument();
  });

  it("warns immediately for mixed types and confirms objectively before commit", () => {
    const onConfirm = vi.fn();
    renderPicker({
      materials: [SINGLE_TYPE_MATERIALS[0], PROFILE_MATERIALS[2]],
      onConfirm,
    });

    fireEvent.click(screen.getByRole("button", { name: "选择 Red PLA" }));
    fireEvent.click(
      screen.getByRole("button", { name: "选择 Black PETG" }),
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("PETG 1 项");
    expect(status).toHaveTextContent("PLA 1 项");

    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    const confirmation = screen.getByRole("alertdialog", {
      name: "确认混合耗材类型？",
    });
    expect(confirmation).toBeInTheDocument();
    expect(confirmation).toHaveTextContent(
      "请确认喷嘴温度、热床温度和层间粘结符合你的打印方案。",
    );
    expect(confirmation).not.toHaveTextContent("新手建议");
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.click(
      within(confirmation).getByRole("button", { name: "返回调整" }),
    );
    expect(
      screen.queryByRole("alertdialog", { name: "确认混合耗材类型？" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/已选耗材：2/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    fireEvent.click(
      screen.getByRole("button", { name: "仍然使用" }),
    );
    expect(onConfirm).toHaveBeenCalledWith([
      "JAYO/red-pla",
      "Other/black-petg",
    ]);
  });

  it("focuses search, closes the confirmation before the main dialog, and restores focus", async () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Open";
    document.body.appendChild(trigger);
    trigger.focus();

    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <MaterialPickerDialog
          open={open}
          materials={[SINGLE_TYPE_MATERIALS[0], PROFILE_MATERIALS[2]]}
          loading={false}
          initialSelected={[]}
          onConfirm={vi.fn()}
          onCancel={() => setOpen(false)}
        />
      );
    }

    render(<Harness />);
    await waitFor(() => {
      expect(screen.getByTestId("material-picker-search-input")).toHaveFocus();
    });

    fireEvent.click(screen.getByRole("button", { name: "选择 Red PLA" }));
    fireEvent.click(
      screen.getByRole("button", { name: "选择 Black PETG" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "选择耗材" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(trigger).toHaveFocus());
    trigger.remove();
  });

  it("shows a retryable loading failure instead of an empty library", () => {
    const onRetry = vi.fn();
    renderPicker({
      materials: [],
      loadError: true,
      onRetry,
    });

    expect(
      screen.getByTestId("material-picker-load-error"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("converter store — selectedMaterialDirNames persistence", () => {
  const KEY = "lumina_selectedMaterialDirNames";
  const BACKING_KEY = "lumina_materialBackingMaterialDirName";

  beforeEach(() => {
    localStorage.clear();
    useConverterStore.setState({
      selectedMaterialDirNames: [],
      materialBackingMaterialDirName: null,
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("writes the latest selection to localStorage when set", () => {
    useConverterStore
      .getState()
      .setSelectedMaterialDirNames(["mat-a", "mat-b"]);
    expect(JSON.parse(localStorage.getItem(KEY) ?? "[]")).toEqual([
      "mat-a",
      "mat-b",
    ]);
  });

  it("overwrites previous persisted value on subsequent updates", () => {
    useConverterStore.getState().setSelectedMaterialDirNames(["mat-a"]);
    useConverterStore
      .getState()
      .setSelectedMaterialDirNames(["mat-c", "mat-d"]);
    expect(JSON.parse(localStorage.getItem(KEY) ?? "[]")).toEqual([
      "mat-c",
      "mat-d",
    ]);
  });

  it("clearing the selection persists an empty array", () => {
    useConverterStore.getState().setSelectedMaterialDirNames(["mat-a"]);
    useConverterStore.getState().setSelectedMaterialDirNames([]);
    expect(localStorage.getItem(KEY)).toBe("[]");
  });

  it("keeps the base plate material inside the selected material list", () => {
    useConverterStore
      .getState()
      .setSelectedMaterialDirNames(["mat-a", "mat-b"]);
    useConverterStore.getState().setMaterialBackingMaterialDirName("mat-b");

    useConverterStore
      .getState()
      .setSelectedMaterialDirNames(["mat-c", "mat-d"]);

    expect(useConverterStore.getState().materialBackingMaterialDirName).toBe(
      "mat-c",
    );
    expect(localStorage.getItem(BACKING_KEY)).toBe("mat-c");
  });

  it("defaults the base plate material to a selected white material", () => {
    useConverterStore.getState().setSelectedMaterialDirNames([
      "brand/pla-green",
      "brand/pla-yellow",
      "brand/pla-white",
    ]);

    expect(useConverterStore.getState().materialBackingMaterialDirName).toBe(
      "brand/pla-white",
    );
  });

  it("detects Chinese white material names for the base plate default", () => {
    useConverterStore.getState().setSelectedMaterialDirNames([
      "瑞贝思/瑞贝思 PLA 绿",
      "瑞贝思/瑞贝思 PLA 白",
    ]);

    expect(useConverterStore.getState().materialBackingMaterialDirName).toBe(
      "瑞贝思/瑞贝思 PLA 白",
    );
  });

  it("changing only the base plate material preserves preview state", () => {
    useConverterStore.setState({
      sessionId: "session-1",
      previewImageUrl: "/preview.png",
      previewGlbUrl: "/preview.glb",
      downloadUrl: "/old.3mf",
      threemfDiskPath: "/tmp/old.3mf",
      selectedMaterialDirNames: ["mat-a", "mat-b"],
      materialBackingMaterialDirName: "mat-a",
    });

    useConverterStore.getState().setMaterialBackingMaterialDirName("mat-b");

    expect(useConverterStore.getState().sessionId).toBe("session-1");
    expect(useConverterStore.getState().previewImageUrl).toBe("/preview.png");
    expect(useConverterStore.getState().previewGlbUrl).toBe("/preview.glb");
    expect(useConverterStore.getState().downloadUrl).toBeNull();
    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
  });
});
