import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import Combobox from "../components/ui/Combobox";

const options = [{ value: "Bambu Lab", label: "拓竹 · Bambu Lab", keywords: "竹子" }, { value: "Aliz", label: "爱丽兹 · Aliz" }];
function Field({ submit = vi.fn() }: { submit?: () => void }) {
  const [value, setValue] = useState("");
  return <form onSubmit={submit}><Combobox label="品牌" value={value} onChange={setValue} options={options} customHint="可直接使用填写的名称" /></form>;
}
it("searches brand aliases and selects by keyboard without submitting the form", () => {
  const submit = vi.fn();
  render(<Field submit={submit} />);
  const input = screen.getByRole("combobox", { name: "品牌" });
  fireEvent.change(input, { target: { value: "竹子" } });
  expect(screen.getByRole("option", { name: "拓竹 · Bambu Lab" })).toBeInTheDocument();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(input).toHaveValue("Bambu Lab");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(submit).not.toHaveBeenCalled();
});
it("keeps a custom brand on Escape and lets focus leave the menu", () => {
  render(<Field />);
  const input = screen.getByRole("combobox", { name: "品牌" });
  fireEvent.change(input, { target: { value: "My new filament" } });
  expect(screen.getByText("可直接使用填写的名称")).toBeInTheDocument();
  fireEvent.keyDown(input, { key: "Escape" });
  expect(input).toHaveValue("My new filament");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  fireEvent.focus(input);
  fireEvent.blur(input);
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});
