# capture_screenshot_script.py
import sys
import asyncio
from pyppeteer import launch

async def screenshot_and_click(page, x, y, screenshot_path):
    await page.screenshot({'path': screenshot_path, 'fullPage': True})
    await page.mouse.click(x, y)
    # await page.waitForNavigation({'waitUntil': 'networkidle2'})
    await asyncio.sleep(1)

async def capture_double_screenshot(url, coord=(649, 528)):
    browser = await launch(args=['--no-sandbox'], executablePath='/usr/bin/chromium')
    page = await browser.newPage()
    await page.goto(url, {'waitUntil': 'networkidle2'})
    await asyncio.sleep(1)
    await page.reload({'waitUntil': 'networkidle2'})
    x, y = coord
    await screenshot_and_click(page, x, y, 'screenshot1.png')
    await screenshot_and_click(page, x, y, 'screenshot2.png')

    await browser.close()

async def capture_screenshot(url, path):
    browser = await launch(args=['--no-sandbox'], executablePath='/usr/bin/chromium')
    page = await browser.newPage()
    await page.goto(url, {'waitUntil': 'networkidle2'})
    await asyncio.sleep(1)
    await page.reload({'waitUntil': 'networkidle2'})
    await page.screenshot({'path': path, 'fullPage': True})
    await browser.close()

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
        asyncio.run(capture_screenshot(url, path))

    elif mode == "double":
        if len(sys.argv) == 5:
            x = int(sys.argv[3])
            y = int(sys.argv[4])
        else:
            x, y = 649, 528
        asyncio.run(capture_double_screenshot(url, (x, y)))

    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
