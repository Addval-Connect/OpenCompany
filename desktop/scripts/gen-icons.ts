/**
 * Render build/icon.svg to build/icon.png (1024x1024). electron-builder
 * derives .icns / .ico / the Linux PNG set from that one PNG, so only the
 * SVG is committed.
 */

import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import sharp from "sharp";

import { DESKTOP_DIR, fail, log } from "./_lib";

const svg = join(DESKTOP_DIR, "build", "icon.svg");
const png = join(DESKTOP_DIR, "build", "icon.png");

if (!existsSync(svg)) fail(`missing ${svg}`);
mkdirSync(join(DESKTOP_DIR, "build"), { recursive: true });

await sharp(svg, { density: 384 }).resize(1024, 1024).png().toFile(png);
log(`icon rendered -> ${png}`);
