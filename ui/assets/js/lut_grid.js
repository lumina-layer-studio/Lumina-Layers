function selectLutColor(hexColor) {
    const container = document.getElementById("conv-lut-color-selected-hidden");
    if (!container) return;
    const input = container.querySelector("textarea, input");
    if (!input) return;

    input.value = hexColor;
    input.dispatchEvent(new Event("input", { bubbles: true }));

    const btn = document.getElementById("conv-lut-color-trigger-btn");
    if (btn) btn.click();
}
