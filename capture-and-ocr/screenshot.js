const express = require('express');
const puppeteer = require('puppeteer');
const { exec } = require('child_process');
const fs = require('fs');               // For streaming methods
const fsp = require('fs').promises;     // For promises-based methods
const path = require('path');

const app = express();
const port = 3000;

const captureScreenshot = async (url) => {
  const screenshotPath = path.join(__dirname, 'screenshot.png');

  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--ignore-certificate-errors', '--disable-gpu'],
    headless: true,
    executablePath: '/usr/bin/chromium'
  });

  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'networkidle2' });
  await page.screenshot({ path: screenshotPath, fullPage: true });
  await browser.close();

  return screenshotPath;
};

app.get('/capture', async (req, res) => {
  const url = req.query.url;
  if (!url) return res.status(400).send('Missing url parameter');

  try {
    const screenshotPath = await captureScreenshot(url);
    const stat = await fsp.stat(screenshotPath);

    res.writeHead(200, {
      'Content-Type': 'image/png',
      'Content-Length': stat.size,
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Pragma': 'no-cache',
      'Expires': '0'
    });

    const readStream = fs.createReadStream(screenshotPath);

    readStream.on('error', (err) => {
      console.error('Error reading screenshot:', err);
      if (!res.headersSent) {
        res.status(500).send({ error: 'Failed to read image' });
      } else {
        res.destroy(err);
      }
    });

    readStream.on('close', () => {
      fs.unlink(screenshotPath, (unlinkErr) => {
        if (unlinkErr) console.error('Error deleting screenshot:', unlinkErr);
      });
    });

    readStream.pipe(res);

  } catch (err) {
    if (!res.headersSent) {
      res.status(500).send({ error: err.message });
    } else {
      console.error('Error after headers sent:', err);
    }
  }
});

app.get('/capture-and-ocr', async (req, res) => {
  const url = req.query.url;
  const tessArgs = req.query.tessArgs || '';
  if (!url) return res.status(400).send('Missing url parameter');

  const ocrOutputPath = path.join(__dirname, 'ocr-result');

  try {
    const screenshotPath = await captureScreenshot(url);

    await new Promise((resolve, reject) => {
      exec(`tesseract ${screenshotPath} ${ocrOutputPath} ${tessArgs}`, (error) => {
        if (error) return reject(error);
        resolve();
      });
    });

    const ocrText = await fsp.readFile(ocrOutputPath + '.txt', 'utf8');
    await fsp.unlink(screenshotPath);
    await fsp.unlink(ocrOutputPath + '.txt');

    res.send(ocrText);

  } catch (err) {
    res.status(500).send({ error: err.message });
  }
});

app.listen(port, () => {
  console.log(`Server started on port ${port}`);
});
