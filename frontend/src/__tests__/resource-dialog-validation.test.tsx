import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ResourceDialog from "../components/ui/ResourceDialog";
import TabNavBar from "../components/widget/TabNavBar";
import SubTabBar from "../components/widget/SubTabBar";

it.each(["", "incomplete-url"])("reveals nested folded fields when native validation rejects %j", async value => {
  const submitted = vi.fn();
  function FoldedForm() {
    const [open, setOpen] = useState(false);
    return <ResourceDialog title="Validation" onClose={vi.fn()} onSubmit={submitted}
      footer={<button type="submit">Submit</button>}>
      <details open={open} onToggle={event => {
        if (event.target === event.currentTarget) setOpen(event.currentTarget.open);
      }}>
        <summary>Channel</summary>
        <details><summary>Purchase links</summary>
          <label>Product URL<input type="url" required defaultValue={value} /></label>
        </details>
      </details>
    </ResourceDialog>;
  }
  render(<FoldedForm />);
  const input = screen.getByLabelText("Product URL");
  expect(input).not.toBeVisible();
  fireEvent.click(screen.getByRole("button", {name:"Submit"}));
  await waitFor(() => expect(input).toBeVisible());
  expect(input.closest("details")?.open).toBe(true);
  expect(input.closest("details")?.parentElement?.closest("details")?.open).toBe(true);
  expect(submitted).not.toHaveBeenCalled();
});

it("submits valid folded values without expanding unrelated sections", () => {
  const submitted = vi.fn(event => event.preventDefault());
  render(<ResourceDialog title="Validation" onClose={vi.fn()} onSubmit={submitted}
    footer={<button type="submit">Submit</button>}>
    <details><summary>Optional links</summary>
      <label>Product URL<input type="url" required defaultValue="https://example.test/product" /></label>
    </details>
  </ResourceDialog>);
  act(() => fireEvent.click(screen.getByRole("button", {name:"Submit"})));
  expect(submitted).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("Product URL")).not.toBeVisible();
});

it("keeps primary navigation names when compact labels are hidden", () => {
  render(<div data-review-nav><style>{"[data-review-nav] .hidden {display:none}"}</style>
    <TabNavBar compact activeTab="material-cloud-sync" onTabChange={vi.fn()} />
  </div>);
  const buttons = screen.getAllByRole("button");
  expect(buttons).toHaveLength(6);
  for (const button of buttons) expect(button).toHaveAccessibleName();
});

it.each(["material-cloud-sync", "lut-library", "converter"] as const)(
  "keeps secondary navigation names in compact %s", activeTab => {
    render(<div data-review-nav><style>{"[data-review-nav] .hidden {display:none}"}</style>
      <SubTabBar compact activeTab={activeTab} onTabChange={vi.fn()} />
    </div>);
    for (const tab of screen.getAllByRole("tab")) expect(tab).toHaveAccessibleName();
  },
);
