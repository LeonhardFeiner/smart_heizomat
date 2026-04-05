# capture_screenshot_script.py
import sys
import asyncio
from pyppeteer import launch
import traceback


async def screenshot_and_click(page, x, y, screenshot_path):
    await page.screenshot({"path": screenshot_path, "fullPage": True})
    await page.mouse.click(x, y)
    # give the page a moment to update after click
    await asyncio.sleep(0.8)


async def capture_double_screenshot(url, coord=(649, 528)):
    browser = None
    try:
        browser = await launch(
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--no-zygote",
                "--disable-setuid-sandbox",
            ],
            executablePath="/usr/bin/chromium",
            headless=True,
        )
        page = await browser.newPage()
        await page.goto(url, {"waitUntil": "networkidle2", "timeout": 30000})
        # allow the noVNC canvas to finish rendering
        await asyncio.sleep(1.5)
        await page.reload({"waitUntil": "networkidle2", "timeout": 30000})
        x, y = coord
        await screenshot_and_click(page, x, y, "screenshot1.png")
        await screenshot_and_click(page, x, y, "screenshot2.png")
    except Exception:
        print(
            "capture_double_screenshot error:\n" + traceback.format_exc(),
            file=sys.stderr,
        )
        raise
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


async def capture_screenshot(url, path):
    browser = None
    try:
        browser = await launch(
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--no-zygote",
                "--disable-setuid-sandbox",
            ],
            executablePath="/usr/bin/chromium",
            headless=True,
        )
        page = await browser.newPage()
        await page.goto(url, {"waitUntil": "networkidle2", "timeout": 30000})
        # allow the noVNC canvas to finish rendering
        await asyncio.sleep(1.5)
        await page.reload({"waitUntil": "networkidle2", "timeout": 30000})
        await page.screenshot({"path": path, "fullPage": True})
    except Exception:
        print("capture_screenshot error:\n" + traceback.format_exc(), file=sys.stderr)
        raise
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    # usage:
    # python capture_screenshot_script.py single <url> <path>
    # python capture_screenshot_script.py double <url> (coords optional, default 649,528)
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python capture_screenshot_script.py single <url> <screenshot_path>")
        print("  python capture_screenshot_script.py double <url> [x] [y]")
        sys.exit(1)

    mode = sys.argv[1]
    url = sys.argv[2]

    if mode == "single":
        if len(sys.argv) != 4:
            print("Single mode requires screenshot path")
            sys.exit(1)
        path = sys.argv[3]
        try:
            asyncio.run(capture_screenshot(url, path))
        except Exception:
            sys.exit(1)

    elif mode == "double":
        if len(sys.argv) == 5:
            x = int(sys.argv[3])
            y = int(sys.argv[4])
        else:
            x, y = 649, 528
        try:
            asyncio.run(capture_double_screenshot(url, (x, y)))
        except Exception:
            sys.exit(1)

    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
