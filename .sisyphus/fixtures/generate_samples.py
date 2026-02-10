"""
Generate synthetic test samples for baseline capture.

Creates three representative sample images:
1. Portrait: Skin tone gradients with facial features simulation
2. High-saturation illustration: Vibrant color stripes and patterns
3. Low-contrast photo: Subtle gray gradients with low dynamic range
"""

import numpy as np
from PIL import Image, ImageDraw
import os

# Output directory
SAMPLE_DIR = ".sisyphus/fixtures/samples"

# Image dimensions (standard test size)
WIDTH, HEIGHT = 400, 300


def create_portrait_sample():
    """
    Create a portrait-like sample with skin tones and facial features.

    Simulates a human portrait with:
    - Skin tone gradients (peach/beige tones)
    - Eye-like dark regions
    - Lip-like red regions
    - Hair-like dark areas
    """
    # Create base skin gradient (top to bottom)
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

    for y in range(HEIGHT):
        # Skin tone gradient: lighter at top, slightly darker at bottom
        factor = y / HEIGHT
        r = int(255 * (0.95 - 0.15 * factor))  # 255 -> 217
        g = int(220 * (0.9 - 0.1 * factor))  # 198 -> 178
        b = int(200 * (0.85 - 0.1 * factor))  # 170 -> 153
        img[y, :] = [r, g, b]

    # Add eye-like regions (dark ovals)
    # Left eye
    for y in range(100, 130):
        for x in range(120, 180):
            if ((x - 150) ** 2) / 30**2 + ((y - 115) ** 2) / 15**2 <= 1:
                img[y, x] = [60, 50, 45]  # Dark brown

    # Right eye
    for y in range(100, 130):
        for x in range(220, 280):
            if ((x - 250) ** 2) / 30**2 + ((y - 115) ** 2) / 15**2 <= 1:
                img[y, x] = [60, 50, 45]  # Dark brown

    # Add lip-like region (reddish)
    for y in range(190, 220):
        for x in range(160, 240):
            if ((x - 200) ** 2) / 40**2 + ((y - 205) ** 2) / 15**2 <= 1:
                img[y, x] = [200, 100, 110]  # Reddish

    # Add hair-like region (dark at top)
    for y in range(0, 80):
        for x in range(WIDTH):
            # Wavy hair pattern
            wave = np.sin(x / 20) * 10
            if y < 60 + wave:
                darkness = max(0, 1 - (y - wave) / 60)
                img[y, x] = img[y, x] * (1 - 0.6 * darkness)
                img[y, x] = img[y, x].astype(np.uint8)

    return Image.fromarray(img)


def create_high_saturation_sample():
    """
    Create a high-saturation illustration sample.

    Features vibrant, saturated colors in geometric patterns:
    - Primary color stripes (red, green, blue)
    - Secondary color regions (yellow, cyan, magenta)
    - High contrast between regions
    """
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

    # Divide into vertical stripes of saturated colors
    stripe_width = WIDTH // 6

    # Stripe 1: Pure Red
    img[:, 0:stripe_width] = [255, 0, 0]

    # Stripe 2: Pure Green
    img[:, stripe_width : 2 * stripe_width] = [0, 255, 0]

    # Stripe 3: Pure Blue
    img[:, 2 * stripe_width : 3 * stripe_width] = [0, 0, 255]

    # Stripe 4: Yellow (Red + Green)
    img[:, 3 * stripe_width : 4 * stripe_width] = [255, 255, 0]

    # Stripe 5: Magenta (Red + Blue)
    img[:, 4 * stripe_width : 5 * stripe_width] = [255, 0, 255]

    # Stripe 6: Cyan (Green + Blue)
    img[:, 5 * stripe_width : 6 * stripe_width] = [0, 255, 255]

    # Add some geometric patterns for interest
    # Horizontal bar with white
    img[120:150, :] = [255, 255, 255]

    # Circular pattern in center
    center_y, center_x = HEIGHT // 2, WIDTH // 2
    for y in range(HEIGHT):
        for x in range(WIDTH):
            dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
            if 50 < dist < 70:
                img[y, x] = [255, 255, 255]  # White circle outline

    return Image.fromarray(img)


def create_low_contrast_sample():
    """
    Create a low-contrast photo-like sample.

    Features subtle tonal variations:
    - Narrow dynamic range (gray values 120-180)
    - Smooth gradient transitions
    - Minimal color saturation
    """
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

    # Create subtle gradient from light gray to medium gray
    for x in range(WIDTH):
        factor = x / WIDTH
        # Very narrow range: 120-180 (out of 0-255)
        base = 120 + int(60 * factor)

        # Add slight variation between channels for minimal color
        r = base + 5
        g = base
        b = base - 5

        img[:, x] = [r, g, b]

    # Add some subtle patterns (low contrast)
    # Horizontal bands with very subtle brightness variation
    img_int16 = img.astype(np.int16)  # Convert to int16 to avoid overflow
    for y in range(0, HEIGHT, 30):
        brightness_variation = 10
        for dy in range(15):
            if y + dy < HEIGHT:
                img_int16[y + dy, :] = np.clip(
                    img_int16[y + dy, :] + brightness_variation, 0, 255
                )
                brightness_variation = -brightness_variation  # Alternate
    img = img_int16.astype(np.uint8)  # Convert back to uint8

    return Image.fromarray(img)


def main():
    """Generate all sample images."""
    os.makedirs(SAMPLE_DIR, exist_ok=True)

    print(f"Generating test samples in {SAMPLE_DIR}/")

    # Generate portrait sample
    portrait = create_portrait_sample()
    portrait_path = os.path.join(SAMPLE_DIR, "sample1_portrait.png")
    portrait.save(portrait_path)
    print(f"  [OK] {portrait_path}")

    # Generate high-saturation sample
    high_sat = create_high_saturation_sample()
    high_sat_path = os.path.join(SAMPLE_DIR, "sample2_high_saturation.png")
    high_sat.save(high_sat_path)
    print(f"  [OK] {high_sat_path}")

    # Generate low-contrast sample
    low_contrast = create_low_contrast_sample()
    low_contrast_path = os.path.join(SAMPLE_DIR, "sample3_low_contrast.png")
    low_contrast.save(low_contrast_path)
    print(f"  [OK] {low_contrast_path}")

    print("\nAll sample images generated successfully!")
    print("\nSample characteristics:")
    print("  1. Portrait: Skin tones, facial features, hair simulation")
    print("  2. High-saturation: Vibrant primary/secondary colors")
    print("  3. Low-contrast: Subtle gray gradients, narrow dynamic range")


if __name__ == "__main__":
    main()
