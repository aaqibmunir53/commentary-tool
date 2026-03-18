"""Quick test: download an already-rendered video from HeyGen /projects page."""

import os
import time
from playwright.sync_api import sync_playwright

BROWSER_PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".heygen_chrome_profile")
UNIQUE_TITLE = "CommentaryAI_1773788325"
OUTPUT_PATH = "/tmp/test_download.mp4"


def test_download():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            BROWSER_PROFILE_DIR,
            headless=False,
            viewport={"width": 1920, "height": 1080},
            accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Go to projects page
        print("Navigating to /projects...")
        page.goto("https://app.heygen.com/projects", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        # Find the title element
        print(f"Looking for '{UNIQUE_TITLE}'...")
        title_el = page.locator(f'text="{UNIQUE_TITLE}"').first
        if not title_el.is_visible(timeout=5000):
            print("ERROR: Title not visible!")
            context.close()
            return

        # Step 1: Hover over THUMBNAIL area (above the title text)
        bb = title_el.bounding_box()
        if not bb:
            print("ERROR: Could not get bounding box")
            context.close()
            return

        print(f"Title bounding box: {bb}")
        print(f"Hovering thumbnail at ({bb['x'] + bb['width']/2}, {bb['y'] - 120})...")
        page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] - 120)
        page.wait_for_timeout(2000)

        # Step 2: Find and HOVER the three-dot menu button
        # The icon is iconpark-icon[name="more-level"] inside a button
        print("Looking for three-dot menu button (more-level)...")
        dots_hovered = False

        # Primary: find button with more-level icon
        try:
            btn = page.locator('button:has(iconpark-icon[name="more-level"])').first
            if btn.is_visible(timeout=2000):
                print(f"  Found! Hovering...")
                btn.hover()
                dots_hovered = True
        except Exception:
            pass

        if not dots_hovered:
            print("  Not found by selector, trying JS position...")
            dots_pos = page.evaluate("""(title) => {
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    if (el.children.length === 0 && el.textContent.trim() === title) {
                        let card = el;
                        for (let i = 0; i < 10; i++) {
                            card = card.parentElement;
                            if (!card) break;
                            const icons = card.querySelectorAll('iconpark-icon[name="more-level"]');
                            for (const icon of icons) {
                                const btn = icon.closest('button');
                                if (btn) {
                                    const rect = btn.getBoundingClientRect();
                                    return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
                                }
                            }
                        }
                        return null;
                    }
                }
                return null;
            }""", UNIQUE_TITLE)
            if dots_pos:
                print(f"  Found at ({dots_pos['x']}, {dots_pos['y']}), hovering...")
                page.mouse.move(dots_pos["x"], dots_pos["y"])
                dots_hovered = True

        if not dots_hovered:
            print("ERROR: Could not find three-dot menu button")
            page.screenshot(path="/tmp/test_download_debug.png")
            page.wait_for_timeout(10000)
            context.close()
            return

        page.wait_for_timeout(2000)
        page.screenshot(path="/tmp/test_download_after_dots_hover.png")
        print("Screenshot saved after hovering three-dot button")

        # Step 3: Look for "Download" in the dropdown
        print("Looking for Download option...")
        dl_option = page.locator('text="Download"').first
        try:
            if not dl_option.is_visible(timeout=3000):
                print("  Not visible after hover — trying CLICK instead...")
                btn = page.locator('button:has(iconpark-icon[name="more-level"])').first
                btn.click()
                page.wait_for_timeout(2000)
                page.screenshot(path="/tmp/test_download_after_dots_click.png")
                print("  Screenshot saved after clicking three-dot button")

                if not dl_option.is_visible(timeout=3000):
                    print("ERROR: Download still not visible")
                    page.wait_for_timeout(10000)
                    context.close()
                    return
        except Exception as e:
            print(f"ERROR: {e}")
            page.wait_for_timeout(10000)
            context.close()
            return

        # Step 4: Click "Download" in the dropdown — opens a download dialog
        print("Clicking Download in dropdown (opens dialog)...")
        dl_option.click()
        page.wait_for_timeout(3000)

        # Step 5: Click the big cyan "Download" button in the dialog
        print("Looking for Download button in dialog...")
        page.screenshot(path="/tmp/test_download_dialog.png")

        try:
            # The dialog has a big cyan Download button — it's a different element
            # from the dropdown option. Find the large button with "Download" text.
            dialog_dl_btn = page.locator('button:has-text("Download")').last
            if dialog_dl_btn.is_visible(timeout=3000):
                print("Found dialog Download button, clicking...")
                with page.expect_download(timeout=120000) as download_info:
                    dialog_dl_btn.click()

                download = download_info.value
                download.save_as(OUTPUT_PATH)

                if os.path.exists(OUTPUT_PATH):
                    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
                    print(f"SUCCESS! Downloaded to {OUTPUT_PATH} ({size_mb:.1f} MB)")
                else:
                    print("ERROR: File not saved")
            else:
                print("ERROR: Dialog Download button not visible")
        except Exception as e:
            print(f"ERROR downloading: {e}")

        page.wait_for_timeout(3000)
        context.close()


if __name__ == "__main__":
    test_download()
