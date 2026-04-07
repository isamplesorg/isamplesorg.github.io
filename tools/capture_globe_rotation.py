#!/usr/bin/env python3
"""
Capture a rotating globe animation from a standalone Cesium page.
Produces animated WebP (via img2webp) and GIF (via ffmpeg).

Prerequisites:
    pip install playwright
    playwright install chromium
    brew install webp ffmpeg   # for img2webp and ffmpeg

Usage:
    # 1. Serve this directory locally:
    python -m http.server 8765 --directory tools/

    # 2. Run the capture:
    python tools/capture_globe_rotation.py

    # 3. Output lands in /tmp/isamples_globe.webp (copy to assets/)

Tunable parameters:
    --frames 120     Number of frames (more = smoother but larger file)
    --duration 15    Loop duration in seconds (higher = slower rotation)
    --width 800      Viewport width
    --height 500     Viewport height
    --quality 40     WebP quality (0-100, lower = smaller file)
"""

import asyncio
import argparse
import os
import shutil
import tempfile
import math


async def capture_globe(num_frames=120, duration_sec=15, output_path="/tmp/isamples_globe.webp",
                        width=800, height=500, quality=40,
                        url="http://localhost:8765/globe_capture.html"):
    from playwright.async_api import async_playwright

    frame_dir = tempfile.mkdtemp(prefix="globe_frames_")

    print(f"Capturing {num_frames} frames for {duration_sec}s animation at {width}x{height}")
    print(f"URL: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--enable-webgl', '--use-gl=swiftshader']
        )
        page = await browser.new_page(viewport={"width": width, "height": height})
        page.on("console", lambda msg: None)  # suppress noise

        print("Loading globe page...")
        await page.goto(url, wait_until="networkidle", timeout=120000)

        # Wait for DuckDB data to load
        print("Waiting for Cesium + data...")
        try:
            await page.wait_for_function("() => window._dataLoaded === true", timeout=60000)
            print("Data loaded!")
        except Exception as e:
            print(f"Data load timeout ({e}) — checking viewer anyway")

        # Let imagery tiles render
        await page.wait_for_timeout(5000)

        # Verify viewer is accessible
        has_viewer = await page.evaluate("() => !!window._viewer && !!window._viewer.scene")
        if not has_viewer:
            print("ERROR: Cesium viewer not accessible")
            await browser.close()
            return

        cluster_count = await page.evaluate("""
            () => {
                const prims = window._viewer.scene.primitives;
                let total = 0;
                for (let i = 0; i < prims.length; i++) {
                    try { if (prims.get(i).length) total += prims.get(i).length; } catch(e) {}
                }
                return total;
            }
        """)
        print(f"Points on globe: {cluster_count}")

        # Full 360° rotation spread across all frames
        rotation_per_frame = (2 * math.pi) / num_frames

        print("Capturing frames...")
        for i in range(num_frames):
            await page.evaluate(f"""
                () => {{
                    window._viewer.scene.camera.rotate(
                        Cesium.Cartesian3.UNIT_Z,
                        {rotation_per_frame}
                    );
                }}
            """)

            # Wait for Cesium to render the frame
            await page.evaluate("""
                () => new Promise(resolve => {
                    window._viewer.scene.requestRender();
                    requestAnimationFrame(() => requestAnimationFrame(resolve));
                })
            """)
            await page.wait_for_timeout(40)

            frame_path = os.path.join(frame_dir, f"frame_{i:04d}.png")
            await page.screenshot(path=frame_path)

            if (i + 1) % 30 == 0 or i == 0:
                print(f"  Frame {i+1}/{num_frames}")

        await browser.close()

    print(f"\nAll {num_frames} frames captured. Stitching...")

    # ms per frame for the target duration
    ms_per_frame = int((duration_sec / num_frames) * 1000)

    # Animated WebP via img2webp (ffmpeg's libwebp_anim doesn't produce
    # proper multi-frame WebP reliably)
    frame_glob = os.path.join(frame_dir, "frame_*.png")
    cmd_webp = (
        f'img2webp -loop 0 -lossy -q {quality} -d {ms_per_frame} '
        f'{frame_glob} -o "{output_path}"'
    )
    os.system(cmd_webp)

    # Animated GIF fallback via ffmpeg
    fps = num_frames / duration_sec
    gif_path = output_path.replace('.webp', '.gif')
    cmd_gif = (
        f'ffmpeg -y -framerate {fps} -i "{frame_dir}/frame_%04d.png" '
        f'-vf "scale={width}:-1:flags=lanczos,split[s0][s1];'
        f'[s0]palettegen=max_colors=64[p];[s1][p]paletteuse=dither=bayer" '
        f'-loop 0 "{gif_path}" 2>/dev/null'
    )
    os.system(cmd_gif)

    # Static fallback frame
    static_path = output_path.replace('.webp', '_static.png')
    shutil.copy(os.path.join(frame_dir, "frame_0000.png"), static_path)

    # Report
    print("\nOutput files:")
    for f in [output_path, gif_path, static_path]:
        if os.path.exists(f):
            size_mb = os.path.getsize(f) / 1024 / 1024
            print(f"  {os.path.basename(f)}: {size_mb:.1f} MB")

    shutil.rmtree(frame_dir)
    print(f"\nDone! Copy {output_path} to assets/isamples_globe.webp to deploy.")


def main():
    parser = argparse.ArgumentParser(description="Capture rotating globe animation")
    parser.add_argument("--frames", type=int, default=120, help="Number of frames (default: 120)")
    parser.add_argument("--duration", type=float, default=15.0, help="Animation duration in seconds (default: 15)")
    parser.add_argument("--output", default="/tmp/isamples_globe.webp", help="Output path")
    parser.add_argument("--width", type=int, default=800, help="Width in pixels (default: 800)")
    parser.add_argument("--height", type=int, default=500, help="Height in pixels (default: 500)")
    parser.add_argument("--quality", type=int, default=40, help="WebP quality 0-100 (default: 40)")
    parser.add_argument("--url", default="http://localhost:8765/globe_capture.html", help="Page URL")
    args = parser.parse_args()

    asyncio.run(capture_globe(
        num_frames=args.frames,
        duration_sec=args.duration,
        output_path=args.output,
        width=args.width,
        height=args.height,
        quality=args.quality,
        url=args.url
    ))


if __name__ == "__main__":
    main()
